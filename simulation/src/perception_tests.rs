use crate::*;

thread_local! {
    pub(super) static UNSHARED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}
fn unshared<T>(work: impl FnOnce() -> T) -> T {
    struct Restore(bool);
    impl Drop for Restore {
        fn drop(&mut self) { UNSHARED.with(|v| v.set(self.0)); }
    }
    let _restore = Restore(UNSHARED.with(|v| v.replace(true)));
    work()
}

#[test]
fn shared_death_payload_preserves_world_events_and_custom_visibility_faults() {
    for source in [include_str!("../../scenarios/survival.json"),
        include_str!("../../scenarios/luna-arena-matrix.json"),
        include_str!("../../scenarios/faction-world-reality.json")] {
        for client in [false, true] {
            for custom in [None, Some("fn visible(c) { c.viewer.empathy > 30 }"),
                Some("fn visible(c) { c.viewer.id == 2 || c.other.id == 3 }"),
                Some("fn visible(c) { throw \"original witness-law failure\"; }")] {
                let mut world = World::new("shared-death-parity".into(), serde_json::from_str(source).unwrap()).unwrap();
                world.enable_participants();
                if client { world.enable_client_controllers().unwrap(); }
                if let Some(source) = custom {
                    let artifact = laws::compile(&laws::LawDraft {interface_version:1,source:source.into()}).unwrap();
                    world.laws.active.insert("universal".into(),1);
                    world.laws.history.entry("universal".into()).or_default().insert(1,laws::LawRevision {
                        reference:laws::LawRef {scope:laws::LawScope::Universal,revision:1},
                        artifact,author:1,origin:1,installed_ms:0,
                    });
                }
                let mut reference = world.clone();
                let cause = world.players[0].last_cause.unwrap_or(1);
                assert_eq!(world.damage(0,100,None,cause,"attack"),
                    unshared(||reference.damage(0,100,None,cause,"attack")));
                assert_eq!(world.flush_law_faults(),reference.flush_law_faults());
                assert_eq!(serde_json::to_value(&world).unwrap(),serde_json::to_value(&reference).unwrap());
                assert_eq!(serde_json::to_value(&world.events).unwrap(),serde_json::to_value(&reference.events).unwrap());
            }
        }
    }
}

#[test]
fn witnesses_share_payload_but_keep_individual_causal_evidence_and_memory() {
    let mut scenario: Scenario = serde_json::from_str(include_str!("../../scenarios/population-reproduction.json")).unwrap();
    let template = scenario.players[0].clone();
    scenario.players = (1..=24).map(|id| { let mut p=template.clone();p.id=id;p }).collect();
    scenario.arenas[0].actors = (1..=24).collect();
    scenario.arenas[0].controllers.clear();
    scenario.lifecycle.as_mut().unwrap().max_total = 32;
    scenario.starting_behaviors.clear();
    let mut world=World::new("shared-death-evidence".into(),scenario).unwrap();
    world.enable_participants();
    // Include both memory-based and client controllers in the same delivery.
    for i in 1..12 {world.enable_actor_client(i).unwrap();}
    let cause=world.players[0].last_cause.unwrap_or(1);
    world.damage(0,100,None,cause,"attack").unwrap();
    let events: Vec<_> = world.events.iter().filter(|e|e.kind=="perception" && e.data["kind"]=="death").collect();
    assert_eq!(events.len(),23);
    for event in &events {
        assert!(event.data.same_snapshot(&events[0].data));
        let actor=event.actor.unwrap();
        assert_ne!(actor,1);
        let state=&world.participants[&actor];
        let personal=state.experiences.iter().find(|e|e.source==event.id).unwrap();
        assert!(personal.data.same_snapshot(&event.data));
        assert_eq!(personal.location,world.players.iter().find(|p|p.id==actor).unwrap().position);
        if !world.client_controlled(actor) {
            assert!(world.players.iter().find(|p|p.id==actor).unwrap().memories.iter()
                .any(|m|m.source==event.id && m.kind=="death" && m.from==Some(1)));
        }
    }
    let ids: std::collections::BTreeSet<_> = events.iter().map(|e|e.id).collect();
    assert_eq!(ids.len(),23,"each witness retains a distinct personal event");
    assert!(!world.participants[&1].experiences.iter().any(|e|e.kind=="perception" && e.data["kind"]=="death"));
}
