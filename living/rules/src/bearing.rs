//! Where something is from where one stands, in the words every scene and prompt uses
//! (talk-places, docs/COMMUNICATION.md §20): the eight compass words of the scene's `dir`, and
//! a place's distance and direction ("49 m south", "here"). One source for the authority's
//! scene and the mind's place lists, so a deliberation and a talk turn give the same way.

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

/// How far and which way `to` is from `from`: "49 m south", or "here" within [`HERE_M`].
pub fn from_here(from: (f32, f32), to: (f32, f32)) -> String {
    let d = ((to.0 - from.0).powi(2) + (to.1 - from.1).powi(2)).sqrt();
    if d <= HERE_M {
        return "here".into();
    }
    format!("{:.0} m {}", d.round(), direction(from, to))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_place_is_here_or_metres_and_a_compass_word() {
        assert_eq!(from_here((416.0, 239.9), (403.5, 284.5)), "46 m south");
        assert_eq!(from_here((100.0, 100.0), (103.0, 102.0)), "here");
        assert_eq!(from_here((100.0, 100.0), (90.0, 90.0)), "14 m northwest");
        assert_eq!(from_here((0.0, 0.0), (30.0, 0.0)), "30 m east");
        assert_eq!(direction((0.0, 0.0), (0.2, 0.1)), "here");
        assert_eq!(direction((0.0, 0.0), (0.0, -10.0)), "north");
        assert_eq!(direction((0.0, 0.0), (10.0, 10.0)), "southeast");
    }
}
