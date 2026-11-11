//! Who is under the cursor: one pick for everything that asks (play-test 5 check, 2026-11-11:
//! with two people overlapping on screen, the nameplate named the one in front while Enter spoke
//! to the one behind, because each asked its own way).
//!
//! - **The rule:** a body is under the cursor when the cursor is inside its outline on screen
//!   (feet to head as drawn, about a shoulder's width either side). When several are, the one
//!   drawn in front (nearest the camera) is picked, as the eye sees it.
//! - **Small or far bodies:** with nobody's outline under the cursor, the body standing nearest
//!   the cursor's ground point within [`NEAR_GROUND_M`] is picked (the old hover rule), so a
//!   distant person a few pixels tall can still be pointed at.
//! - **Who reads it:** the hover and the nameplates (`ui/live.rs`), whom Enter addresses
//!   (`ui/say.rs`), and combat's target (`combat::pick`: a tap on a peaceful person, F, the
//!   target plate), which falls back to its own aim assist only when nobody is under the cursor.
//! - **When:** after the camera has moved and the cursor's ground point is known
//!   ([`crate::phase::Phase::Camera`]), so the next frame's input and UI read the same pick.

use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;

/// With no outline under the cursor, a body within this distance (m) of its ground point.
pub const NEAR_GROUND_M: f32 = 1.2;
/// Half a body's width on screen, in metres at the body's distance.
const HALF_WIDTH_M: f32 = 0.35;
/// The narrowest half-width (px), so a far body stays pointable.
const MIN_HALF_PX: f32 = 6.0;
/// Bodies considered: within this distance of me (m), as the nameplates.
const RANGE_M: f32 = 40.0;
/// A drawn height when the body's own is not known yet (m).
const DEFAULT_HEIGHT_M: f32 = 1.75;

/// The pick, for every reader this frame.
#[derive(Resource, Default, Debug)]
pub struct Pick {
    /// The character under the cursor, if any.
    pub under: Option<u32>,
    /// The bodies it chose among (for the UI dump: where each was on screen).
    pub seen: Vec<Seen>,
}

/// A body as the camera sees it this frame.
#[derive(Clone, Copy, Debug)]
pub struct Seen {
    pub id: u32,
    /// Feet and head in viewport px (y grows downward).
    pub feet: Vec2,
    pub head: Vec2,
    /// Its drawn height (m), to turn metres into pixels at its distance.
    pub height: f32,
    /// Distance from the camera (m): the smaller is drawn in front.
    pub depth: f32,
    /// Distance from the cursor's ground point (m), if there is one.
    pub ground: Option<f32>,
}

impl Seen {
    /// Whether the cursor is inside this body's outline on screen.
    pub fn contains(&self, c: Vec2) -> bool {
        let ppm = (self.feet.y - self.head.y).abs() / self.height.max(0.1);
        let half = (HALF_WIDTH_M * ppm).max(MIN_HALF_PX);
        let (left, right) = (self.feet.x.min(self.head.x) - half, self.feet.x.max(self.head.x) + half);
        let (top, bottom) = (self.feet.y.min(self.head.y) - 0.15 * ppm, self.feet.y.max(self.head.y) + 0.1 * ppm);
        c.x >= left && c.x <= right && c.y >= top && c.y <= bottom
    }
}

/// The body under the cursor: the front-most whose outline holds it, else the nearest within
/// [`NEAR_GROUND_M`] of the cursor's ground point. Ties go to the nearer to the camera, then the
/// lower id, so two bodies stacked on one spot give the same answer every frame (the bodies come
/// in the scene's map order, which is not stable).
pub fn choose(cursor: Vec2, bodies: &[Seen]) -> Option<u32> {
    bodies
        .iter()
        .filter(|b| b.contains(cursor))
        .min_by(|a, b| a.depth.total_cmp(&b.depth).then(a.id.cmp(&b.id)))
        .or_else(|| bodies.iter().filter(|b| b.ground.is_some_and(|g| g < NEAR_GROUND_M)).min_by(|a, b| a.ground.unwrap_or(f32::MAX).total_cmp(&b.ground.unwrap_or(f32::MAX)).then(a.depth.total_cmp(&b.depth)).then(a.id.cmp(&b.id))))
        .map(|b| b.id)
}

pub struct PickPlugin;

impl Plugin for PickPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Pick>()
            .add_systems(Update, update.in_set(crate::phase::Phase::Camera).after(crate::camera::follow).after(crate::live::ground_cursor));
    }
}

/// Fill [`Pick`] from the bodies drawn round me and where the cursor is.
#[allow(clippy::too_many_arguments)]
pub fn update(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    cam: Res<crate::camera::Cam>,
    target: Res<crate::controls::Target>,
    pointer: Res<crate::pointer::Pointer>,
    (sight, town, combat): (Res<crate::sight::Sight>, Res<crate::town::Town>, Res<crate::combat::Combat>),
    (island, live): (Option<Res<crate::island::Island>>, Res<crate::live::Live>),
    cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>,
    mut pick: ResMut<Pick>,
) {
    pick.under = None;
    pick.seen.clear();
    let (Some(cursor), Some(me_at)) = (pointer.pos, target.0) else { return };
    let Ok((camera, gtf)) = cams.single() else { return };
    let me = net.my_id;
    let me2 = Vec2::new(me_at.x, me_at.z);
    let ground = cam.cursor_ground.map(|g| Vec2::new(g.x, g.z));
    let eye = gtf.translation();
    let mut bodies = Vec::new();
    for (id, (p, _)) in &scene.shown {
        if Some(*id) == me || town.hidden(*id) || combat.deaths.contains_key(id) || p.distance(me2) > RANGE_M || !sight.shows(me2, *p) {
            continue;
        }
        let height = live.heights.get(id).copied().unwrap_or(DEFAULT_HEIGHT_M);
        let feet = match &island {
            Some(i) => Vec3::new(p.x, i.height(p.x, p.y), p.y),
            None => scene.at3(p.x, p.y),
        };
        let head = feet + Vec3::Y * height;
        let (Ok(f), Ok(h)) = (camera.world_to_viewport(gtf, feet), camera.world_to_viewport(gtf, head)) else { continue };
        bodies.push(Seen { id: *id, feet: f, head: h, height, depth: eye.distance((feet + head) * 0.5), ground: ground.map(|g| g.distance(*p)) });
    }
    pick.under = choose(cursor, &bodies);
    pick.seen = bodies;
}

#[cfg(test)]
mod tests {
    use super::*;

    fn body(id: u32, x: f32, feet_y: f32, px_tall: f32, depth: f32, ground: Option<f32>) -> Seen {
        Seen { id, feet: Vec2::new(x, feet_y), head: Vec2::new(x, feet_y - px_tall), height: 1.75, depth, ground }
    }

    #[test]
    fn the_body_in_front_wins_where_two_overlap() {
        // #2 stands in front (nearer the camera, drawn lower and larger); #3 behind it, drawn
        // higher. The cursor on #2's chest is inside both outlines; its ground point lies by #3.
        let front = body(2, 800.0, 600.0, 175.0, 9.0, Some(1.3));
        let behind = body(3, 805.0, 560.0, 150.0, 10.4, Some(0.1));
        let chest = Vec2::new(800.0, 480.0);
        assert!(front.contains(chest) && behind.contains(chest));
        assert_eq!(choose(chest, &[behind, front]), Some(2));
        assert_eq!(choose(chest, &[front, behind]), Some(2));
    }

    #[test]
    fn two_bodies_on_one_spot_give_one_answer_in_any_order() {
        // Stacked exactly (the talk scene's two residents walked onto one spot): the nearer to
        // the camera wins, and with equal depth the lower id, whatever order they come in.
        let tall = body(3, 707.0, 542.0, 79.0, 20.469, Some(0.4));
        let short = body(2, 707.0, 542.0, 78.0, 20.475, Some(0.4));
        let at = Vec2::new(707.0, 520.0);
        assert_eq!(choose(at, &[short, tall]), Some(3));
        assert_eq!(choose(at, &[tall, short]), Some(3));
        let (a, b) = (body(5, 707.0, 542.0, 78.0, 20.0, Some(0.4)), body(4, 707.0, 542.0, 78.0, 20.0, Some(0.4)));
        assert_eq!(choose(at, &[a, b]), Some(4));
        assert_eq!(choose(at, &[b, a]), Some(4));
        // Off both outlines, by the ground point: the same rule.
        let far = Vec2::new(100.0, 100.0);
        assert_eq!(choose(far, &[a, b]), Some(4));
    }

    #[test]
    fn the_one_behind_where_only_it_is_under_the_cursor() {
        let front = body(2, 800.0, 600.0, 175.0, 9.0, Some(2.0));
        let behind = body(3, 805.0, 560.0, 150.0, 10.4, Some(0.4));
        // Above the front one's head, on the one behind's.
        let head = Vec2::new(805.0, 402.0);
        assert!(!front.contains(head) && behind.contains(head));
        assert_eq!(choose(head, &[front, behind]), Some(3));
    }

    #[test]
    fn off_every_outline_the_nearest_ground_point_within_reach() {
        let far = body(5, 300.0, 300.0, 12.0, 38.0, Some(0.8));
        let other = body(6, 900.0, 300.0, 12.0, 38.0, Some(1.0));
        assert_eq!(choose(Vec2::new(330.0, 310.0), &[other, far]), Some(5));
        let gone = body(7, 300.0, 300.0, 12.0, 38.0, Some(NEAR_GROUND_M + 0.1));
        assert_eq!(choose(Vec2::new(500.0, 500.0), &[gone]), None);
    }
}
