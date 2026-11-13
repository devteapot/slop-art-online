//! The one sight rule (docs/PERCEPTION.md, "The field of view"): whether an eye sees a spot.
//!
//! Pure, so the authority (every perception path: players' perceived sets, minds' percepts and
//! scenes, behaviour graphs, the combat feed, a player's aimed act) and the game client (its
//! sight display) decide by the same function. Its inputs are the observer's senses now (the
//! script's `senses(a)` law: sight, hearing and, when the world's `fov_on` law is on, a `field`),
//! where the eye is and which way the body faces (`body.heading` at the instant, by
//! `steer::pose`), the spot and its distance, the light on the target (the `glow` law), and
//! whether the target is already seen (the margins that keep someone at an edge from
//! flickering).
//!
//! Without a field the rule is the one the authority had before: within the wider of the
//! observer's sight and the target's glow (plus the keep margin when already seen) and a clear
//! sight line ([`Map::sight_clear`]). With a field, how far one sees depends on the angle off
//! facing: full sight (or a light's glow) within `focal_deg`, `side_share` of it (or the glow)
//! out to `side_deg`, and nothing beyond, except all round within `near_m`. Someone already
//! seen keeps `margin_deg` more on each angle, as they keep the keep margin on the distance.

use crate::map::Map;
use crate::steer::wrap;

/// How the eye's view narrows away from facing (`senses(a).field`; degrees off the heading on
/// either side, metres). Every value is the world's law (`fov_*` in `laws()`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Field {
    /// Full sight within this angle of facing.
    pub focal_deg: f32,
    /// Side vision out to this angle.
    pub side_deg: f32,
    /// How far side vision reaches, as a share of sight.
    pub side_share: f32,
    /// All round within this distance (the law gives less in the dark).
    pub near_m: f32,
    /// Someone already seen stays seen this many degrees past an edge.
    pub margin_deg: f32,
}

/// What a creature senses now (`senses(a)`): how far it sees and hears, in tiles (a tile is one
/// metre), and how its view narrows away from facing (none: the same in every direction).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Senses {
    pub sight: f32,
    pub hearing: f32,
    pub field: Option<Field>,
}

impl Senses {
    /// Senses without a field (sight the same all round).
    pub fn round(sight: f32, hearing: f32) -> Self {
        Self { sight, hearing, field: None }
    }
}

/// How far an eye with `senses` sees in a direction `off` radians from where its body faces, a
/// target with `glow` (the `glow` law: 0 without a light on it). `kept` is the keep margin in
/// metres when the target is already seen (`keep_seen_m`), else `None`. A client draws the
/// field from this.
pub fn reach(senses: &Senses, off: f32, glow: f32, kept: Option<f32>) -> f32 {
    let keep = kept.unwrap_or(0.0);
    let lit = senses.sight.max(glow);
    let Some(f) = senses.field else { return lit + keep };
    let margin = if kept.is_some() { f.margin_deg } else { 0.0 };
    let deg = wrap(off).abs().to_degrees();
    let ahead = if deg <= f.focal_deg + margin {
        lit
    } else if deg <= f.side_deg + margin {
        (senses.sight * f.side_share).max(glow)
    } else {
        0.0
    };
    ahead.max(f.near_m.min(senses.sight)) + keep
}

/// Whether an eye at `eye`, its body facing `heading` (radians, `body.heading`), with `senses`,
/// sees `at`, `dist` away: within [`reach`] in that direction and with a clear sight line. `glow`
/// is the light on the target; `kept` the keep margin when it is already seen.
#[allow(clippy::too_many_arguments)]
pub fn sees(map: &Map, eye: (f32, f32), heading: f32, at: (f32, f32), dist: f32, senses: &Senses, glow: f32, kept: Option<f32>) -> bool {
    within(eye, heading, at, dist, senses, glow, kept) && map.sight_clear(eye, at)
}

/// The distance and angle part of [`sees`], without the sight line.
pub fn within(eye: (f32, f32), heading: f32, at: (f32, f32), dist: f32, senses: &Senses, glow: f32, kept: Option<f32>) -> bool {
    // Inside the nearest reach the field allows in any direction, the angle does not matter.
    let floor = match senses.field {
        None => senses.sight.max(glow),
        Some(f) => f.near_m.min(senses.sight),
    } + kept.unwrap_or(0.0);
    if dist <= floor {
        return true;
    }
    if senses.field.is_none() {
        return false;
    }
    dist <= reach(senses, off_facing(eye, heading, at), glow, kept)
}

/// The angle (radians, -π..π) between where a body at `eye` faces and the direction to `at`.
pub fn off_facing(eye: (f32, f32), heading: f32, at: (f32, f32)) -> f32 {
    wrap((at.1 - eye.1).atan2(at.0 - eye.0) - heading)
}

/// The way `to` lies from `from` in the words a scene uses ("north", "southeast", "here"): one
/// source for what a character perceives and for its remembered places (`+y` is south).
pub fn direction_word(from: (f32, f32), to: (f32, f32)) -> &'static str {
    let (dx, dy) = (to.0 - from.0, to.1 - from.1);
    if dx.abs() < 0.5 && dy.abs() < 0.5 {
        return "here";
    }
    match dy.atan2(dx).to_degrees() {
        a if (-22.5..22.5).contains(&a) => "east",
        a if (22.5..67.5).contains(&a) => "southeast",
        a if (67.5..112.5).contains(&a) => "south",
        a if (112.5..157.5).contains(&a) => "southwest",
        a if (-67.5..-22.5).contains(&a) => "northeast",
        a if (-112.5..-67.5).contains(&a) => "north",
        a if (-157.5..-112.5).contains(&a) => "northwest",
        _ => "west",
    }
}

/// A distance in the words a scene uses: whole metres (tiles) up to 30, then rough, to the
/// nearest ten. Things in sight are always near, so they read as before.
pub fn rough_dist(d: f32) -> f32 {
    if d < 30.0 {
        d.round()
    } else {
        (d / 10.0).round() * 10.0
    }
}

/// The eight compass ways, clockwise from north (`+y` is south on the world's map).
pub const COMPASS8: [&str; 8] = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];

/// Which of the eight compass ways `to` lies from `from` (0 north, clockwise; `+y` is south).
pub fn compass8(from: (f32, f32), to: (f32, f32)) -> u8 {
    // North is -y: an angle measured clockwise from north.
    let a = (to.0 - from.0).atan2(-(to.1 - from.1));
    (((a.to_degrees() + 360.0 + 22.5) % 360.0) / 45.0) as u8 % 8
}

/// How a sound's distance is told: 0 near, 1 close, 2 far (the world's `heard_near_m` and
/// `heard_close_m` laws).
pub fn heard_band(dist: f32, near_m: f32, close_m: f32) -> u8 {
    if dist <= near_m {
        0
    } else if dist <= close_m {
        1
    } else {
        2
    }
}

/// Scene key under which a mind's scene lists what it hears but does not see (while its sight
/// has a field).
pub const HEARD: &str = "you hear (out of sight)";

/// What a listener is told of a sound, in a person's words: what it sounds like, where it is
/// from the way the body faces and by the compass, and how far ("a person, behind you to the
/// south-west, close").
pub fn heard_words(kind: &str, eye: (f32, f32), heading: f32, at: (f32, f32), band: u8) -> (String, String, &'static str) {
    let what = if kind == "creature" { "something moving".to_string() } else { format!("{} {kind}", if kind.starts_with(['a', 'e', 'i', 'o', 'u']) { "an" } else { "a" }) };
    let way = COMPASS8[compass8(eye, at) as usize];
    let rel = relative(off_facing(eye, heading, at));
    (what, format!("{rel}, to the {way}"), HEARD_BANDS[band.min(2) as usize])
}

/// The words for a heard band.
pub const HEARD_BANDS: [&str; 3] = ["near", "close", "far"];

/// Where something lies relative to where a body faces, in a person's words: "ahead", "to your
/// left", "to your right", "behind you" (+y is south, so a positive angle off facing turns
/// clockwise on the map: to the right).
pub fn relative(off: f32) -> &'static str {
    let d = off.to_degrees();
    if d.abs() <= 45.0 {
        "ahead"
    } else if d.abs() >= 135.0 {
        "behind you"
    } else if d > 0.0 {
        "to your right"
    } else {
        "to your left"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::map::{Map, Terrain};

    fn open() -> Map {
        Map { w: 64, h: 64, tiles: vec![Terrain::Grass as u8; 64 * 64], blocked: Default::default(), opaque: Default::default(), nav: Default::default() }
    }

    /// The shipped starting values (`laws()`'s `fov_*`) by day.
    fn day() -> Senses {
        Senses { sight: 11.0, hearing: 9.0, field: Some(Field { focal_deg: 70.0, side_deg: 110.0, side_share: 1.0 / 3.0, near_m: 3.0, margin_deg: 10.0 }) }
    }

    /// A spot `d` metres away at `deg` degrees off an eye at (32, 32) facing east.
    fn at(deg: f32, d: f32) -> (f32, f32) {
        let a = deg.to_radians();
        (32.0 + d * a.cos(), 32.0 + d * a.sin())
    }

    fn sees_at(s: &Senses, deg: f32, d: f32, glow: f32, kept: Option<f32>) -> bool {
        sees(&open(), (32.0, 32.0), 0.0, at(deg, d), d, s, glow, kept)
    }

    #[test]
    fn the_field_has_three_zones_and_the_near_ring() {
        let s = day();
        // Focal: full sight within ±70°.
        assert!(sees_at(&s, 0.0, 10.9, 0.0, None));
        assert!(sees_at(&s, 69.0, 10.9, 0.0, None) && sees_at(&s, -69.0, 10.9, 0.0, None));
        assert!(!sees_at(&s, 0.0, 11.1, 0.0, None));
        // Side: a third of sight out to ±110°.
        assert!(sees_at(&s, 90.0, 3.6, 0.0, None) && sees_at(&s, -109.0, 3.6, 0.0, None));
        assert!(!sees_at(&s, 90.0, 3.8, 0.0, None) && !sees_at(&s, 75.0, 5.0, 0.0, None));
        // Behind: only the near ring.
        assert!(sees_at(&s, 180.0, 2.9, 0.0, None) && sees_at(&s, 130.0, 2.9, 0.0, None));
        assert!(!sees_at(&s, 180.0, 3.1, 0.0, None) && !sees_at(&s, 111.0, 3.5, 0.0, None));
    }

    #[test]
    fn the_margin_keeps_someone_seen_past_each_edge() {
        let s = day();
        // 75° is beyond the focal edge: not seen afresh at 8 m, kept when already seen.
        assert!(!sees_at(&s, 75.0, 8.0, 0.0, None));
        assert!(sees_at(&s, 75.0, 8.0, 0.0, Some(1.0)));
        assert!(!sees_at(&s, 81.0, 8.0, 0.0, Some(1.0)), "the margin is 10°");
        // Past the side edge, and the keep metre on the distance.
        assert!(!sees_at(&s, 115.0, 3.5, 0.0, None) && sees_at(&s, 115.0, 3.5, 0.0, Some(1.0)));
        assert!(sees_at(&s, 0.0, 11.9, 0.0, Some(1.0)) && !sees_at(&s, 0.0, 12.1, 0.0, Some(1.0)));
        assert!(sees_at(&s, 180.0, 3.9, 0.0, Some(1.0)), "the near ring keeps the metre too");
    }

    #[test]
    fn glow_shows_a_lit_figure_only_in_the_field() {
        // Night: sight 6, near 2 in the dark; a lit figure glows 28 m.
        let mut s = day();
        s.sight = 6.0;
        s.field.as_mut().unwrap().near_m = 2.0;
        assert!(sees_at(&s, 0.0, 25.0, 28.0, None), "ahead, lit");
        assert!(sees_at(&s, 100.0, 25.0, 28.0, None), "in side vision, lit");
        assert!(!sees_at(&s, 150.0, 25.0, 28.0, None), "behind, lit: not seen");
        assert!(!sees_at(&s, 150.0, 2.5, 28.0, None) && sees_at(&s, 150.0, 1.9, 28.0, None));
        // Without a field the glow is seen all round, as before.
        let round = Senses::round(6.0, 9.0);
        assert!(sees_at(&round, 150.0, 25.0, 28.0, None));
    }

    #[test]
    fn without_a_field_the_answer_is_the_old_rule() {
        // The old rule: `dist <= max(sight, glow) (+ keep when seen) && map.sight_clear`.
        let mut m = open();
        for y in 0..64 {
            m.set(40, y, Terrain::Wall);
        }
        let old = |eye: (f32, f32), to: (f32, f32), d: f32, sight: f32, glow: f32, kept: Option<f32>| d <= sight.max(glow) + kept.unwrap_or(0.0) && m.sight_clear(eye, to);
        let eye = (32.0, 32.0);
        let mut n = 0;
        for sight in [6.0, 9.0, 11.0, 48.0] {
            for glow in [0.0, 28.0] {
                for kept in [None, Some(1.0)] {
                    for i in 0..360 {
                        for d in [0.0, 0.5, 2.0, 5.9, 6.1, 10.0, 11.5, 20.0, 30.0] {
                            for heading in [0.0, 1.0, -2.5] {
                                let a = (i as f32).to_radians();
                                let to = (eye.0 + d * a.cos(), eye.1 + d * a.sin());
                                let s = Senses::round(sight, 9.0);
                                assert_eq!(sees(&m, eye, heading, to, d, &s, glow, kept), old(eye, to, d, sight, glow, kept), "{sight} {glow} {kept:?} {i}° {d}");
                                n += 1;
                            }
                        }
                    }
                }
            }
        }
        assert!(n > 100_000);
    }

    #[test]
    fn walls_hide_inside_the_field_too() {
        let mut m = open();
        m.set(36, 32, Terrain::Wall);
        assert!(!sees(&m, (32.5, 32.5), 0.0, (40.5, 32.5), 8.0, &day(), 0.0, None));
        // The near ring sees round, not through.
        assert!(!sees(&m, (35.5, 32.5), std::f32::consts::PI, (37.5, 32.5), 2.0, &day(), 0.0, None));
    }

    #[test]
    fn direction_and_distance_words() {
        assert_eq!(direction_word((10.0, 10.0), (10.2, 10.1)), "here");
        assert_eq!(direction_word((10.0, 10.0), (20.0, 10.0)), "east");
        assert_eq!(direction_word((10.0, 10.0), (10.0, 0.0)), "north");
        assert_eq!(direction_word((10.0, 10.0), (0.0, 20.0)), "southwest");
        assert_eq!((rough_dist(7.4), rough_dist(29.4), rough_dist(34.0), rough_dist(246.0)), (7.0, 29.0, 30.0, 250.0));
    }

    #[test]
    fn compass_bands_and_words() {
        let o = (10.0, 10.0);
        assert_eq!(COMPASS8[compass8(o, (10.0, 0.0)) as usize], "north");
        assert_eq!(COMPASS8[compass8(o, (20.0, 10.0)) as usize], "east");
        assert_eq!(COMPASS8[compass8(o, (0.0, 20.0)) as usize], "south-west");
        assert_eq!(COMPASS8[compass8(o, (3.0, 3.0)) as usize], "north-west");
        assert_eq!((heard_band(5.0, 5.0, 15.0), heard_band(5.1, 5.0, 15.0), heard_band(15.1, 5.0, 15.0)), (0, 1, 2));
        // Facing east: south (+y) is to the right.
        assert_eq!(relative(off_facing(o, 0.0, (10.0, 20.0))), "to your right");
        assert_eq!(relative(off_facing(o, 0.0, (0.0, 10.0))), "behind you");
    }
}
