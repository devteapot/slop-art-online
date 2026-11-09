//! Measurement switches (`LIVING_GAME_PERF=<flag>,…`) that turn one rendering cost off at a time,
//! to find where frame time goes. They are for measurement only:
//! - `noedges`: the finishing pass's edge lines and rim;
//! - `nooutlines`: shell outlines (characters);
//! - `noshadows`: the sun's shadow maps;
//! - `noprepass`: depth and normal prepasses (also disables edges, which need them);
//! - `nobloom`: bloom;
//! - `nopeople`: no characters on the island;
//! - `nosmall`: no small things (grass, flowers, props under 1.6 m) on the island.
//!
//! `LIVING_GAME_FPS_CAP=<hz>` sets the headless loop's rate (default 60; 0 runs uncapped, so
//! frame times show the real cost).

use bevy::prelude::*;

pub fn has(flag: &str) -> bool {
    std::env::var("LIVING_GAME_PERF").is_ok_and(|v| v.split(',').any(|f| f.trim() == flag))
}

pub fn cap() -> std::time::Duration {
    let hz: f64 = std::env::var("LIVING_GAME_FPS_CAP").ok().and_then(|v| v.parse().ok()).unwrap_or(60.0);
    if hz <= 0.0 {
        std::time::Duration::ZERO
    } else {
        std::time::Duration::from_secs_f64(1.0 / hz)
    }
}

/// Apply the switches to the camera, the sun and the style each frame (cheap; they only write
/// when something differs).
pub fn apply(
    mut commands: Commands,
    mut style: ResMut<crate::style::Style>,
    mut suns: Query<&mut DirectionalLight>,
    cams: Query<(Entity, Has<bevy::core_pipeline::prepass::DepthPrepass>, Has<bevy::post_process::bloom::Bloom>), With<Camera3d>>,
) {
    if std::env::var("LIVING_GAME_PERF").is_err() {
        return;
    }
    if (has("noedges") || has("noprepass")) && style.edges {
        style.edges = false;
    }
    if has("nooutlines") && style.outlines {
        style.outlines = false;
    }
    if has("noshadows") {
        for mut s in &mut suns {
            if s.shadow_maps_enabled {
                s.shadow_maps_enabled = false;
            }
        }
    }
    for (e, prepass, bloom) in &cams {
        if has("noprepass") && prepass {
            commands.entity(e).remove::<(bevy::core_pipeline::prepass::DepthPrepass, bevy::core_pipeline::prepass::NormalPrepass)>();
        }
        if has("nobloom") && bloom {
            commands.entity(e).remove::<bevy::post_process::bloom::Bloom>();
        }
    }
}
