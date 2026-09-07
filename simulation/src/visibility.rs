//! Conservative candidates for a verified law. Every retained candidate still
//! executes ordinary visibility; custom laws retain the complete query domain.
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

impl World {
    fn visibility_plan(&self, viewer: usize, kind: &str) -> (Vec<usize>, Option<laws::LawBinding>) {
        #[cfg(test)]
        if FORCE_FULL_SCAN.with(|v| v.get()) { return ((0..self.players.len()).collect(), None); }
        let binding = self.law_binding_at(Some(self.players[viewer].position));
        let bounded = self.scripts.api_version == scripting::API_VERSION
            && BUNDLED_CONTRACT.with(|v| *v)
            && self.scripts.definition(&binding.base).is_ok_and(|law|
                law.dependencies.is_empty() && law.source == include_str!("../scripts/law.rhai"))
            && self.law_layers(&binding).is_ok_and(|layers|
                layers.iter().all(|(_, artifact)| !artifact.hooks.iter().any(|h| h == "visible")));
        if !bounded { return ((0..self.players.len()).collect(), None); }
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
                let a = &self.players[viewer];
                let b = &self.players[other];
                // The verified hook reads only id/health. The same Rhai source
                // evaluates them; this removes unused JSON fields, not rules.
                self.same_arena(a.id, b.id) && self.bound_law(binding, "visible", json!({
                    "viewer":{"id":a.id,"health":a.health}, "other":{"id":b.id,"health":b.health},
                    "kind":kind, "distance":self.initial.map.as_ref().map_or_else(
                        ||(a.position-b.position).abs(), |map|map.distance(a.position,b.position))
                }))?
            } else { self.visible(viewer, other, kind)? };
            if allowed { visible.push(other); }
        }
        Ok(visible)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
