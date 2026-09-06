//! Server-side presentation projection. No observer information is sent to participant clients.
use crate::{Event, World};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn law_inspector(world: &World, actor: u32) -> Value {
    let facts = world.law_research_facts(actor);
    if facts.is_null() { return Value::Null; }
    json!({"effective_binding":facts["effective_binding"],"scopes":facts["scopes"]})
}

pub fn snapshot(world: &World, observer: bool, actor: u32, events: &[Event]) -> Value {
    let index = world.players.iter().position(|p| p.id == actor);
    if !observer && index.is_none() {
        return Value::Null;
    }
    let players: Vec<Value> = if observer {
        world
            .players
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let context = world.context(i);
                let mut value = context["player"].clone();
                value["recent_activity"] = context["recent_activity"].clone();
                value["starting_behavior"] = context["starting_behavior"].clone();
                value["local_lifecycle"] = context["lifecycle"].clone();
                value["body"] = context["body"].clone();
                value["infrastructure"] = context["infrastructure"].clone();
                value["research"] = context["research"].clone();
                value["laws"] = law_inspector(world, p.id);
                value["society"] = context["society"].clone();
                value["controller"] = json!(p.controller);
                if let Some(arena)=world.arena_for_actor(p.id) {
                    value["arena"]=json!(arena.label);
                    value["runtime"]=json!(arena.controllers.get(&p.id));
                }
                value
            })
            .collect()
    } else {
        let index = index.unwrap();
        let me = &world.players[index];
        let context = world.context(index);
        let mut own = context["player"].clone();
        own["recent_activity"] = context["recent_activity"].clone();
        own["starting_behavior"] = context["starting_behavior"].clone();
        own["local_lifecycle"] = context["lifecycle"].clone();
        own["body"] = context["body"].clone();
        own["infrastructure"] = context["infrastructure"].clone();
        own["research"] = context["research"].clone();
        own["laws"] = law_inspector(world, me.id);
        own["society"] = context["society"].clone();
        own["controller"] = json!(me.controller);
        let mut visible = BTreeMap::new();
        for memory in &me.memories {
            if memory.kind == "seen_player" && memory.tick == world.tick {
                if let Some(id) = memory.from {
                    visible.insert(id, json!({"id":id,"name":memory.content["name"],"position":memory.location,"controller":"other"}));
                }
            }
        }
        std::iter::once(own).chain(visible.into_values()).collect()
    };
    let sites = if observer {
        json!(world.sites.iter().map(|site| {
            let mut value=json!(site);
            value["food_source"]=json!(world.initial.food_sources.iter().find(|s|s.position==site.position));
            value
        }).collect::<Vec<_>>())
    } else {
        let me = &world.players[index.unwrap()];
        let mut known = BTreeMap::new();
        for memory in &me.site_observations {
            if memory.kind == "site" {
                known.insert(memory.location, json!({"position":memory.location,"food":memory.content["food"],"shelter":memory.content["shelter"],"food_source":memory.content["food_source"],"archives":memory.content["archives"],"lifecycle":memory.content["lifecycle"],"infrastructure":memory.content["infrastructure"],"observed_tick":memory.tick}));
            }
        }
        json!(known.into_values().collect::<Vec<_>>())
    };
    let history: Vec<Value> = if observer {
        events.iter().rev().take(180).rev().map(|e| {
            let mut v = json!(e);
            // Full provider exchanges remain in operator journals, not the rendering payload.
            if e.kind == "model_result" { v["data"] = json!({"request_id":e.data["request_id"],"outcome":e.data["metadata"]["outcome"],"error":e.data["metadata"]["error"]}); }
            if e.kind == "model_request" { v["data"].as_object_mut().map(|o|o.remove("context")); v["data"].as_object_mut().map(|o|o.remove("base_system_prompt")); }
            v
        }).collect()
    } else {
        world.players[index.unwrap()].memories.iter().map(|m|json!({"id":m.source,"tick":m.tick,"actor":actor,"kind":m.kind,"parents":[],"data":m.content})).collect()
    };
    let projection=json!({"run":world.run,"tick":world.tick,"time_ms":world.timing.time_ms,"updates":world.timing.updates,"clock_unit_ms":crate::timing::LEGACY_UNIT_MS,"stopped":world.stopped,"max_ticks":world.initial.max_ticks,
        "map":if observer {world.initial.map.clone()} else {world.map_for_actor(actor)},"arenas":if observer {json!(world.initial.arenas)} else {Value::Null},"can_participate":world.players.iter().any(|p| p.id == 3 && p.controller == crate::Controller::Human),"rules":world.version,"actor":if observer {Value::Null} else {json!(actor)},"observer":observer,"players":players,"sites":sites,"archives":if observer {json!(world.archives)} else {json!(world.players[index.unwrap()].site_observations.iter().filter(|m|m.kind=="site").flat_map(|m|m.content["archives"].as_array().into_iter().flatten().cloned()).collect::<Vec<_>>())},"workshops":if observer {json!(world.initial.lifecycle.as_ref().map(|l|l.workshops.clone()).unwrap_or_default())} else {json!(world.players[index.unwrap()].site_observations.iter().filter(|m|m.kind=="site" && m.content["lifecycle"]["workshop"]==true).map(|m|m.location).collect::<Vec<_>>())},"events":history,
        "regions":world.society_survey(if observer {None} else {Some(actor)}),
        "pending":if observer {json!(world.pending.iter().map(|p|json!({"id":p.id,"actor":p.actor,"tick":p.tick})).collect::<Vec<_>>())} else {Value::Null}});
    if observer {projection} else {crate::research::redacted(projection)}
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn participant_projection_excludes_other_minds_hidden_sites_audit_and_requests() {
        let scenario = serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
        let mut world = World::new("sim-view-test".into(), scenario).unwrap();
        world.step();
        let participant = snapshot(&world, false, 3, &world.events);
        assert!(!participant["observer"].as_bool().unwrap());
        for p in participant["players"].as_array().unwrap() {
            if p["id"] != 3 {
                assert!(p.get("beliefs").is_none());
                assert!(p.get("health").is_none());
            }
        }
        for site in participant["sites"].as_array().unwrap() {
            assert!(site.get("hazard").is_none());
        }
        assert!(participant["pending"].is_null());
        assert!(!participant.to_string().contains("model_request"));
        assert!(snapshot(&world, true, 3, &world.events)["sites"][2]
            .get("hazard")
            .is_some());
        assert!(snapshot(&world, false, 999, &world.events).is_null());
    }

    // Test-only source and evidence; live scenarios never receive these records.
    fn law_world() -> World {
        let mut scenario: crate::Scenario = serde_json::from_str(include_str!("../../scenarios/infrastructure-baseline.json")).unwrap();
        scenario.society = Some(serde_json::from_value(json!({"version":1,"regions":[
            {"id":"west","label":"West","kind":"homeland","bounds":{"x":1,"y":1,"width":7,"height":10},"territorial_editors":[1],"priority":0},
            {"id":"east","label":"East","kind":"homeland","bounds":{"x":8,"y":1,"width":7,"height":10},"territorial_editors":[3],"priority":0}
        ],"organizations":[],"offices":[]})).unwrap());
        let mut world = World::new("law-view-fixture".into(), scenario).unwrap();
        world.enable_participants();
        world
    }
    fn own(projection: &Value, actor: u32) -> &Value {
        projection["players"].as_array().unwrap().iter().find(|p| p["id"] == actor).unwrap()
    }
    fn inspect(world: &mut World, actor: u32, operation: crate::infrastructure::InfrastructureOperation) {
        let i = world.idx(actor).unwrap();
        let action = crate::Action { infrastructure: Some(operation.clone()), ..crate::Action::new(crate::Skill::Infrastructure) };
        let effect = crate::scripting::Effect::Infrastructure { operation };
        world.validate_script_effect(i, &action, &effect).unwrap();
        let cause = world.event(Some(actor), "law_view_fixture", vec![], json!({}));
        world.apply_script_effect(i, cause, effect).unwrap();
    }
    #[test]
    fn law_projection_has_only_local_scopes_and_personal_initial_grant() {
        let mut world = law_world();
        for (actor, granted) in [(1, true), (2, false)] {
            let view = snapshot(&world, false, actor, &world.events);
            let laws = &own(&view, actor)["laws"];
            let scopes = laws["scopes"].as_array().unwrap();
            assert_eq!(scopes.len(), 2);
            let west = scopes.iter().find(|s| s["scope"]["region"] == "west").unwrap();
            assert_eq!(west["revision"], 0);
            assert_eq!(west["local_grant"], granted);
            assert!(laws["effective_binding"]["digest"].is_string());
            assert!(!laws.to_string().contains("east"));
            for other in view["players"].as_array().unwrap().iter().filter(|p| p["id"] != actor) {
                assert!(other.get("laws").is_none());
                assert!(other.get("knowledge").is_none());
            }
        }
        world.players[2].position = 88;
        let view = snapshot(&world, false, 3, &world.events);
        assert!(own(&view, 3)["laws"].to_string().contains("east"));
        assert!(!own(&view, 3)["laws"].to_string().contains("west"));
    }
    #[test]
    fn law_sources_require_own_explicit_inspection_and_private_experiments_stay_separate() {
        use crate::{knowledge::Record, laws::{self, LawDraft, LawRef, LawRevision, LawScope}, law_research::{LawCase, LawEvidence}, infrastructure::InfrastructureOperation as Op};
        let mut world = law_world();
        let scope = LawScope::Territory { region: "west".into() };
        let source = "// private_source_78309\nfn cost(s){2}";
        let artifact = laws::compile(&LawDraft { interface_version: 1, source: source.into() }).unwrap();
        let origin = world.event(Some(1), "law_view_fixture", vec![], json!({}));
        let code = Record { id:"view-law-code".into(), topic:"Law code".into(), text:"Fixture".into(), location:None, author:1, origin, confidence:50, program:None, experiment:None, law_program:Some(artifact.clone()), law_experiment:None };
        let report = Record { id:"view-law-report".into(), law_program:None, law_experiment:Some(LawEvidence { operator:1, station:1, job:1, scope:scope.clone(), binding:world.law_binding_at(Some(84)), program_hash:artifact.source_hash.clone(), input_hash:"fixture-input".into(), cases:vec![LawCase {hook:"cost".into(),input:json!("private_case_94528"),expected:json!(2)}],results:vec![Ok(json!(2))],successful:true,paid_quanta:3 }), ..code.clone() };
        world.receive_record(0, origin, None, &code, "fixture").unwrap();
        world.receive_record(0, origin, None, &report, "fixture").unwrap();
        world.receive_record(1, origin, Some(1), &code, "fixture").unwrap();
        let view = snapshot(&world, false, 1, &world.events);
        assert!(!view.to_string().contains("private_source_78309"));
        assert!(view.to_string().contains("private_case_94528"));
        assert_eq!(own(&view, 1)["knowledge"].as_array().unwrap().iter().find(|h|h["record"]["id"]=="view-law-report").unwrap()["record"]["law_experiment"]["paid_quanta"], 3);
        let recipient = snapshot(&world, false, 2, &world.events);
        assert!(!recipient.to_string().contains("private_source_78309"));
        assert!(!recipient.to_string().contains("private_case_94528"));
        inspect(&mut world, 2, Op::InspectLaw { station:1, record:code.id.clone() });
        let recipient = snapshot(&world, false, 2, &world.events);
        let p = own(&recipient, 2);
        assert_eq!(p["memories"].as_array().unwrap().iter().find(|m|m["kind"]=="law_inspected").unwrap()["content"]["law_program"]["source"], source);
        let held = p["knowledge"].as_array().unwrap().iter().find(|h|h["record"]["id"]==code.id).unwrap();
        assert!(held["record"]["law_program"].get("source").is_none());
        assert_eq!(held["record"]["law_program"]["source_omitted"], true);
        assert!(!recipient.to_string().contains("private_case_94528"));
        assert!(!snapshot(&world, false, 3, &world.events).to_string().contains("private_source_78309"));
        world.laws.active.insert(scope.key(), 1);
        world.laws.history.entry(scope.key()).or_default().insert(1, LawRevision { reference:LawRef {scope:scope.clone(),revision:1},artifact,author:1,origin,installed_ms:world.timing.time_ms });
        let before = snapshot(&world, false, 3, &world.events);
        assert!(!before.to_string().contains("private_source_78309"));
        inspect(&mut world, 3, Op::InspectInstalledLaw { station:1, scope:scope.clone() });
        let after = snapshot(&world, false, 3, &world.events);
        let memory = own(&after, 3)["memories"].as_array().unwrap().iter().find(|m|m["kind"]=="law_inspected").unwrap();
        assert_eq!(memory["content"]["installed"]["revision"], 1);
        assert_eq!(memory["content"]["installed"]["scope"], json!(scope));
        assert_eq!(memory["content"]["law_program"]["source"], source);
        assert!(!snapshot(&world, false, 4, &world.events).to_string().contains("private_source_78309"));
    }
}
