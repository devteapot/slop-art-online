use std::collections::VecDeque;

use bevy::prelude::*;

use crate::player::{FacingAngle, RemoteVelocity};

/// How far behind "now" we render remote entities. Must be >= one server update
/// interval so there are always two snapshots to interpolate between.
/// At 20 Hz send rate (~50ms between updates), 100ms gives a comfortable 2-snapshot margin.
const INTERP_DELAY: f64 = 0.1;
const BUFFER_CAPACITY: usize = 10;

struct NetSnapshot {
    position: Vec3,
    rotation: f32,
    timestamp: f64,
}

#[derive(Component, Default)]
pub struct InterpolationBuffer {
    snapshots: VecDeque<NetSnapshot>,
}

impl InterpolationBuffer {
    pub fn push(&mut self, position: Vec3, rotation: f32, timestamp: f64) {
        if self.snapshots.len() >= BUFFER_CAPACITY {
            self.snapshots.pop_front();
        }
        self.snapshots.push_back(NetSnapshot {
            position,
            rotation,
            timestamp,
        });
    }
}

fn lerp_angle(a: f32, b: f32, t: f32) -> f32 {
    let diff = (b - a + std::f32::consts::PI).rem_euclid(std::f32::consts::TAU)
        - std::f32::consts::PI;
    a + diff * t
}

/// Interpolate remote entities between buffered server snapshots.
///
/// Renders at `now - INTERP_DELAY` so there are (usually) two snapshots to lerp
/// between. When the buffer runs dry (player stopped sending), holds at the
/// newest known position — no extrapolation, no overshoot.
pub fn interpolate_remote_entities(
    time: Res<Time>,
    mut query: Query<(
        &mut Transform,
        &InterpolationBuffer,
        Option<&mut FacingAngle>,
        Option<&mut RemoteVelocity>,
    )>,
) {
    let render_time = time.elapsed_secs_f64() - INTERP_DELAY;

    for (mut transform, buffer, facing, remote_vel) in query.iter_mut() {
        let snapshots = &buffer.snapshots;
        if snapshots.is_empty() {
            continue;
        }

        if snapshots.len() == 1 {
            transform.translation = snapshots[0].position;
            if let Some(mut f) = facing {
                f.0 = snapshots[0].rotation;
            }
            continue;
        }

        let oldest = &snapshots[0];
        let newest = &snapshots[snapshots.len() - 1];

        let (pos, rot, snap_vel) = if render_time <= oldest.timestamp {
            // Before all snapshots — use oldest
            (oldest.position, oldest.rotation, Vec3::ZERO)
        } else if render_time >= newest.timestamp {
            // Past all snapshots (player stopped or updates stalled) — hold at newest, no extrapolation
            (newest.position, newest.rotation, Vec3::ZERO)
        } else {
            // Between two snapshots — interpolate
            let mut result = (newest.position, newest.rotation, Vec3::ZERO);
            for i in 0..snapshots.len() - 1 {
                let a = &snapshots[i];
                let b = &snapshots[i + 1];
                if render_time >= a.timestamp && render_time <= b.timestamp {
                    let dt = b.timestamp - a.timestamp;
                    let t = if dt > 1e-6 {
                        ((render_time - a.timestamp) / dt) as f32
                    } else {
                        1.0
                    };
                    let vel = if dt > 1e-6 {
                        (b.position - a.position) / dt as f32
                    } else {
                        Vec3::ZERO
                    };
                    result = (
                        a.position.lerp(b.position, t),
                        lerp_angle(a.rotation, b.rotation, t),
                        vel,
                    );
                    break;
                }
            }
            result
        };

        // Write snapshot-derived velocity for remote animation driving.
        if let Some(mut rv) = remote_vel {
            rv.0 = snap_vel;
        }

        transform.translation = pos;
        if let Some(mut f) = facing {
            f.0 = rot;
        }
    }
}
