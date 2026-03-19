use bevy::prelude::*;
use shared::module_bindings::StatusEffectType;

use crate::network::{LocalIdentity, StatusEffectEvent, StatusEffectEventQueue};

pub struct ActiveEffect {
    pub scheduled_id: u64,
    pub effect_type: StatusEffectType,
}

#[derive(Resource, Default)]
pub struct LocalStatusEffects(pub Vec<ActiveEffect>);

pub const EFFECT_SLOW_FACTOR: f32 = 0.5;
pub const EFFECT_HASTE_FACTOR: f32 = 1.5;

pub fn speed_multiplier(effects: &LocalStatusEffects) -> f32 {
    let mut mult = 1.0f32;
    for e in &effects.0 {
        match e.effect_type {
            StatusEffectType::Slow => mult = mult.min(EFFECT_SLOW_FACTOR),
            StatusEffectType::Haste => mult = mult.max(EFFECT_HASTE_FACTOR),
            _ => {}
        }
    }
    mult
}

pub fn sync_status_effects(
    queue: Res<StatusEffectEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_effects: ResMut<LocalStatusEffects>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(local_id) = local_id else { return };

    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            StatusEffectEvent::Inserted(effect) => {
                if effect.target_identity == local_id && effect.target_npc_id == 0 {
                    // Remove existing of same type (server replaces, but just in case)
                    local_effects.0.retain(|e| e.effect_type != effect.effect_type);
                    local_effects.0.push(ActiveEffect {
                        scheduled_id: effect.scheduled_id,
                        effect_type: effect.effect_type,
                    });
                }
            }
            StatusEffectEvent::Deleted(effect) => {
                local_effects.0.retain(|e| e.scheduled_id != effect.scheduled_id);
            }
        }
    }
}
