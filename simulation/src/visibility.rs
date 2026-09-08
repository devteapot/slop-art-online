//! Conservative visibility evaluation under an exact source contract. Equivalent
//! witness inputs may reuse a result; custom laws retain full evaluation.
use crate::*;
use sha2::{Digest, Sha256};

thread_local! {
    // These bounds are a dependency contract for these exact bytes, not a second
    // implementation of visibility. Editing the source disables the projection
    // until its contract and differential tests have been reviewed.
    static BUNDLED_CONTRACT: bool = format!("{:x}", Sha256::digest(include_bytes!("../scripts/law.rhai")))
        == "593033f72233dca88d901e271485cd6df5212275519f2d2056111dad85ca4fce";
    #[cfg(test)]
    static FORCE_FULL_SCAN: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// One notification's read-only visibility plan. Do not retain it across physical
/// effects, law activation or arbitrary callbacks that could change its binding.
#[derive(Default)]
pub(super) struct WitnessVisibility {
    domains: BTreeMap<i32, WitnessDomain>,
}
struct WitnessDomain {
    binding: Option<laws::LawBinding>,
    outcomes: BTreeMap<WitnessInputs, bool>,
}
/// The exact bundled hook reads these values. Its only use of IDs is equality;
/// its only modality tests are equality with "death" and "speech". The source
/// hash/definition guard below is required for this input-equivalence contract.
#[derive(PartialEq, Eq, PartialOrd, Ord)]
struct WitnessInputs {
    viewer_health: i32,
    other_health: i32,
    same_identity: bool,
    distance: i32,
    death: bool,
    speech: bool,
}

impl World {
    fn bounded_visibility_binding(&self, position: i32) -> Option<laws::LawBinding> {
        #[cfg(test)]
        if FORCE_FULL_SCAN.with(|v| v.get()) { return None; }
        let binding = self.law_binding_at(Some(position));
        let bounded = self.scripts.api_version == scripting::API_VERSION
            && BUNDLED_CONTRACT.with(|v| *v)
            && self.scripts.definition(&binding.base).is_ok_and(|law|
                law.dependencies.is_empty() && law.source == include_str!("../scripts/law.rhai"))
            && self.law_layers(&binding).is_ok_and(|layers|
                layers.iter().all(|(_, artifact)| !artifact.hooks.iter().any(|h| h == "visible")));
        bounded.then_some(binding)
    }

    fn visibility_plan(&self, viewer: usize, kind: &str) -> (Vec<usize>, Option<laws::LawBinding>) {
        let Some(binding) = self.bounded_visibility_binding(self.players[viewer].position)
            else { return ((0..self.players.len()).collect(), None); };
        let radius = if kind == "speech" { 2 } else { 1 };
        let position = self.players[viewer].position;
        // Preserve original actor order, including self and dead bodies: Rhai
        // still decides health, identity and modality. No knowledge is copied.
        let candidates = self.players.iter().enumerate().filter_map(|(i, other)| {
            let distance = self.initial.map.as_ref().map_or_else(
                || (position - other.position).abs(), |map| map.distance(position, other.position));
            (distance <= radius).then_some(i)
        }).collect();
        (candidates, Some(binding))
    }
    #[cfg(test)]
    fn visibility_candidates(&self, viewer: usize, kind: &str) -> Vec<usize> {
        self.visibility_plan(viewer, kind).0
    }
    pub(super) fn visible_players(&self, viewer: usize, kind: &str) -> Result<Vec<usize>, String> {
        let (candidates, binding) = self.visibility_plan(viewer, kind);
        let mut visible = Vec::new();
        for other in candidates {
            let allowed = if let Some(binding) = &binding {
                self.visible_with_binding(viewer, other, kind, binding)?
            } else { self.visible(viewer, other, kind)? };
            if allowed { visible.push(other); }
        }
        Ok(visible)
    }

    fn visible_with_binding(&self, viewer: usize, other: usize, kind: &str,
        binding: &laws::LawBinding) -> Result<bool, String> {
        let a = &self.players[viewer];
        let b = &self.players[other];
        if !self.same_arena(a.id, b.id) { return Ok(false); }
        // The verified hook reads only id/health. The same Rhai source
        // evaluates them; this removes unused JSON fields, not rules.
        self.bound_law(binding, "visible", json!({
            "viewer":{"id":a.id,"health":a.health}, "other":{"id":b.id,"health":b.health},
            "kind":kind, "distance":self.initial.map.as_ref().map_or_else(
                ||(a.position-b.position).abs(), |map|map.distance(a.position,b.position))
        }))
    }

    pub(super) fn visible_to_witness(&self, viewer: usize, other: usize, kind: &str,
        plan: &mut WitnessVisibility) -> Result<bool, String> {
        let position = self.players[viewer].position;
        let domain = plan.domains.entry(position).or_insert_with(|| WitnessDomain {
            binding: self.bounded_visibility_binding(position), outcomes: BTreeMap::new(),
        });
        if let Some(binding) = &domain.binding {
            let a = &self.players[viewer];
            let b = &self.players[other];
            // Arena permission is checked for every recipient before sharing a
            // pure law result. This does not share perception or personal state.
            if !self.same_arena(a.id, b.id) { return Ok(false); }
            let inputs = WitnessInputs {
                viewer_health: a.health, other_health: b.health, same_identity: a.id == b.id,
                distance: self.initial.map.as_ref().map_or_else(
                    || (a.position-b.position).abs(), |map| map.distance(a.position,b.position)),
                death: kind == "death", speech: kind == "speech",
            };
            if let Some(allowed) = domain.outcomes.get(&inputs) { return Ok(*allowed); }
            // Evaluate the original hook with the first recipient's actual
            // inputs. Only equivalent inputs under the verified source reuse it.
            // Errors are never memoized. Custom definitions use the full path.
            let allowed = self.visible_with_binding(viewer, other, kind, binding)?;
            domain.outcomes.insert(inputs, allowed);
            Ok(allowed)
        } else {
            // Preserve full inputs, call order and quarantine/error semantics
            // for custom visibility, including observations between witnesses.
            self.visible(viewer, other, kind)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn current_targets_survive_memory_eviction_without_creating_memories() {
        let mut scenario: Scenario = serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap();
        let mut person = scenario.players[0].clone();
        person.execution = None;
        scenario.starting_behaviors.clear();
        scenario.players = (1..=24).map(|id| { let mut p=person.clone(); p.id=id; p }).collect();
        let mut world = World::new("crowded-perception".into(),scenario).unwrap();
        assert!(!world.players[0].memories.iter().any(|m|m.from==Some(2)));
        for client in [false,true] {
            if client {world.enable_client_controllers().unwrap();}
            let before = serde_json::to_value(&world.players[0]).unwrap();
            assert!(world.target_perceived(0,2,&[]).unwrap());
            assert_eq!(serde_json::to_value(&world.players[0]).unwrap(),before);
            world.players[1].position += 1000;
            assert!(!world.target_perceived(0,2,&[]).unwrap());
            world.players[1].position = world.players[0].position;
            world.players[1].health = 0;
            assert!(!world.target_perceived(0,2,&[]).unwrap());
            world.players[1].health = 100;
            assert!(!world.target_perceived(0,9999,&[]).unwrap());
        }
    }

    #[test]
    fn current_target_checks_respect_custom_laws_and_arena_boundaries() {
        let mut world = World::new("target-scope".into(),
            serde_json::from_str(include_str!("../../scenarios/luna-arena-matrix.json")).unwrap()).unwrap();
        world.players[2].position = world.players[0].position;
        assert!(!world.target_perceived(0,world.players[2].id,&[]).unwrap());
        world.players[1].position = world.players[0].position;
        assert!(world.target_perceived(0,world.players[1].id,&[]).unwrap());
        let artifact = laws::compile(&laws::LawDraft {interface_version:1,source:"fn visible(c) { false }".into()}).unwrap();
        world.laws.active.insert("universal".into(),1);
        world.laws.history.entry("universal".into()).or_default().insert(1,laws::LawRevision {
            reference:laws::LawRef {scope:laws::LawScope::Universal,revision:1},artifact,author:1,origin:1,installed_ms:0,
        });
        assert!(!world.target_perceived(0,world.players[1].id,&[]).unwrap());
    }

    fn full_scan<T>(work: impl FnOnce() -> T) -> T {
        struct Restore(bool);
        impl Drop for Restore { fn drop(&mut self) { FORCE_FULL_SCAN.with(|v| v.set(self.0)); } }
        let _restore = Restore(FORCE_FULL_SCAN.with(|v| v.replace(true)));
        work()
    }

    #[test]
    fn candidate_filter_preserves_complete_observation_state_and_order() {
        for source in [include_str!("../../scenarios/survival.json"),
            include_str!("../../scenarios/woodland-pathfinding.json"),
            include_str!("../../scenarios/faction-world-reality.json")] {
            let mut world = World::new("sim-visible-equivalence".into(), serde_json::from_str(source).unwrap()).unwrap();
            world.enable_participants();
            for dead in [false, true] {
                if dead { world.players[1].health = 0; }
                for viewer in 0..world.players.len() {
                    for kind in ["sight", "speech", "death", "custom"] {
                        let reference: Vec<_> = (0..world.players.len())
                            .filter(|&other| world.visible(viewer, other, kind).unwrap()).collect();
                        let selected = world.visible_players(viewer, kind).unwrap();
                        assert_eq!(selected, reference);
                    }
                    let mut reference = world.clone();
                    let mut selected = world.clone();
                    full_scan(|| reference.observe_site(viewer)).unwrap();
                    selected.observe_site(viewer).unwrap();
                    assert_eq!(serde_json::to_value(&selected).unwrap(), serde_json::to_value(&reference).unwrap());
                    assert_eq!(serde_json::to_value(&selected.events).unwrap(), serde_json::to_value(&reference.events).unwrap());
                }
            }
        }
    }

    #[test]
    fn edited_base_and_overlay_visibility_keep_full_domain() {
        let mut world = World::new("sim-visible-custom".into(),
            serde_json::from_str(include_str!("../../scenarios/faction-world-reality.json")).unwrap()).unwrap();
        let all: Vec<_> = (0..world.players.len()).collect();
        assert!(world.visibility_candidates(0, "sight").len() < all.len());
        let base = world.scripts.resolve("law").unwrap();
        world.scripts.history.get_mut(&base.id).unwrap().get_mut(&base.revision).unwrap().source.push_str("\n// custom source\n");
        assert_eq!(world.visibility_candidates(0, "sight"), all);
        world.scripts.history.get_mut(&base.id).unwrap().get_mut(&base.revision).unwrap().source = include_str!("../scripts/law.rhai").into();
        let reference = laws::LawRef { scope:laws::LawScope::Universal, revision:1 };
        let artifact = laws::compile(&laws::LawDraft { interface_version:1,
            source:"fn visible(c) { true }".into() }).unwrap();
        world.laws.active.insert("universal".into(), 1);
        world.laws.history.entry("universal".into()).or_default().insert(1, laws::LawRevision {
            reference, artifact, author:1, origin:1, installed_ms:0,
        });
        assert_eq!(world.visibility_candidates(0, "sight"), all);
    }

    #[test]
    fn witness_projection_preserves_death_state_events_and_custom_law_faults() {
        for source in [include_str!("../../scenarios/survival.json"),
            include_str!("../../scenarios/luna-arena-matrix.json"),
            include_str!("../../scenarios/faction-world-reality.json")] {
            for client in [false, true] {
                for custom in [None, Some("fn visible(c) { c.viewer.empathy > 30 }"),
                    Some("fn visible(c) { c.viewer.id == 2 || c.other.id == 3 }"),
                    Some("fn visible(c) { throw \"original witness-law failure\"; }")] {
                    let mut world = World::new("witness-projection-parity".into(), serde_json::from_str(source).unwrap()).unwrap();
                    world.enable_participants();
                    if client { world.enable_client_controllers().unwrap(); }
                    if let Some(source) = custom {
                        let artifact = laws::compile(&laws::LawDraft {interface_version:1, source:source.into()}).unwrap();
                        world.laws.active.insert("universal".into(), 1);
                        world.laws.history.entry("universal".into()).or_default().insert(1, laws::LawRevision {
                            reference:laws::LawRef {scope:laws::LawScope::Universal,revision:1},
                            artifact, author:1, origin:1, installed_ms:0,
                        });
                    }
                    let mut reference = world.clone();
                    let cause = world.players[0].last_cause.unwrap_or(1);
                    let actor = world.players[0].id;
                    let expected = full_scan(|| reference.damage(0, 100, None, cause, "attack"));
                    let actual = world.damage(0, 100, None, cause, "attack");
                    assert_eq!(actual, expected);
                    assert_eq!(world.players[0].health, 0);
                    assert!(world.events.iter().any(|e|e.actor==Some(actor) && e.kind=="death"));
                    assert_eq!(world.flush_law_faults(), reference.flush_law_faults());
                    assert!(serde_json::to_value(&world.events).unwrap()==serde_json::to_value(&reference.events).unwrap(),
                        "original ordered witness and fault evidence");
                    assert!(serde_json::to_value(&world).unwrap()==serde_json::to_value(&reference).unwrap(),
                        "complete personal and physical state");
                }
            }
        }
    }

    #[test]
    fn witness_result_reuse_preserves_health_identity_distance_and_modality() {
        let mut world = World::new("witness-input-equivalence".into(),
            serde_json::from_str(include_str!("../../scenarios/survival.json")).unwrap()).unwrap();
        assert!(world.players.len() >= 3);
        let mut plan = WitnessVisibility::default();
        for health in [0, 1, 37, 100] {
            world.players[0].health = health;
            world.players[1].health = health;
            for target_health in [-1, 0, 50] {
                world.players[2].health = target_health;
                for distance in [0, 1, 2, 3] {
                    world.players[0].position = 0;
                    world.players[1].position = 0;
                    world.players[2].position = distance;
                    for kind in ["death", "speech", "sight", "other"] {
                        for viewer in 0..3 {
                            for other in 0..3 {
                                assert_eq!(world.visible_to_witness(viewer, other, kind, &mut plan),
                                    world.visible(viewer, other, kind),
                                    "health={health}, target={target_health}, distance={distance}, kind={kind}, viewer={viewer}, other={other}");
                            }
                        }
                    }
                }
            }
        }
    }
}
