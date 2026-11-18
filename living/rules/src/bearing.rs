//! Where something is from where one stands, in the words every scene and prompt uses
//! (talk-places, docs/COMMUNICATION.md §20): the eight compass words of the scene's `dir`, and
//! a place's distance and direction ("50 m south", "here"). One source for the authority's
//! scene (what is in sight and remembered places, docs/MOVEMENT_MIND.md step 3) and the mind's
//! place lists, so a deliberation and a talk turn give the same way and the same distance.

/// Within this many metres a place is "here".
pub const HERE_M: f32 = 4.0;

/// The compass word from `from` toward `to` (map coordinates: +y is south), or "here" within half a metre.
pub fn direction(from: (f32, f32), to: (f32, f32)) -> &'static str {
    let dx = to.0 - from.0;
    let dy = to.1 - from.1;
    if dx.abs() < 0.5 && dy.abs() < 0.5 {
        return "here";
    }
    let a = dy.atan2(dx).to_degrees();
    match a {
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
/// nearest ten. Things in sight are always near, so they read exactly; a far place reads as
/// far as one would judge it.
pub fn rough_dist(d: f32) -> f32 {
    if d < 30.0 {
        d.round()
    } else {
        (d / 10.0).round() * 10.0
    }
}

/// How far and which way `to` is from `from`: "50 m south", or "here" within [`HERE_M`].
pub fn from_here(from: (f32, f32), to: (f32, f32)) -> String {
    let d = ((to.0 - from.0).powi(2) + (to.1 - from.1).powi(2)).sqrt();
    if d <= HERE_M {
        return "here".into();
    }
    format!("{:.0} m {}", rough_dist(d), direction(from, to))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_place_is_here_or_metres_and_a_compass_word() {
        assert_eq!(from_here((416.0, 239.9), (403.5, 284.5)), "50 m south");
        assert_eq!(from_here((0.0, 0.0), (0.0, 29.4)), "29 m south");
        assert_eq!(from_here((100.0, 100.0), (103.0, 102.0)), "here");
        assert_eq!(from_here((100.0, 100.0), (90.0, 90.0)), "14 m northwest");
        assert_eq!(from_here((0.0, 0.0), (30.0, 0.0)), "30 m east");
        assert_eq!(direction((0.0, 0.0), (0.2, 0.1)), "here");
        assert_eq!(direction((0.0, 0.0), (0.0, -10.0)), "north");
        assert_eq!(direction((0.0, 0.0), (10.0, 10.0)), "southeast");
        assert_eq!(direction((10.0, 10.0), (0.0, 20.0)), "southwest");
        assert_eq!((rough_dist(7.4), rough_dist(29.4), rough_dist(34.0), rough_dist(246.0)), (7.0, 29.0, 30.0, 250.0));
    }
}
