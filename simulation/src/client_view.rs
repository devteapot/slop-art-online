//! Server-side presentation projection. No observer information is sent to participant clients.
use crate::{Event, World};
use serde_json::{json, Value};
use std::collections::BTreeMap;

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
                known.insert(memory.location, json!({"position":memory.location,"food":memory.content["food"],"shelter":memory.content["shelter"],"food_source":memory.content["food_source"],"archives":memory.content["archives"],"observed_tick":memory.tick}));
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
    json!({"run":world.run,"tick":world.tick,"time_ms":world.timing.time_ms,"updates":world.timing.updates,"clock_unit_ms":crate::timing::LEGACY_UNIT_MS,"stopped":world.stopped,"max_ticks":world.initial.max_ticks,
        "map":if observer {world.initial.map.clone()} else {world.map_for_actor(actor)},"arenas":if observer {json!(world.initial.arenas)} else {Value::Null},"can_participate":world.players.iter().any(|p| p.id == 3 && p.controller == crate::Controller::Human),"rules":world.version,"actor":if observer {Value::Null} else {json!(actor)},"observer":observer,"players":players,"sites":sites,"archives":if observer {json!(world.archives)} else {json!(world.players[index.unwrap()].site_observations.iter().filter(|m|m.kind=="site").flat_map(|m|m.content["archives"].as_array().into_iter().flatten().cloned()).collect::<Vec<_>>())},"events":history,
        "pending":if observer {json!(world.pending.iter().map(|p|json!({"id":p.id,"actor":p.actor,"tick":p.tick})).collect::<Vec<_>>())} else {Value::Null}})
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
}
