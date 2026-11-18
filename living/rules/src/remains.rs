//! Words for the unnamed remains noticed in one look.

/// Groups are in the order of their nearest remains, with singular labels.
pub fn counted_line(groups: &[(&str, usize)], (distance, direction): (f32, &str)) -> String {
    let parts: Vec<_> = groups
        .iter()
        .map(|&(label, count)| {
            let noun = match (label, count) {
                (_, 1) | ("deer" | "sheep" | "fish", _) => label.to_owned(),
                ("wolf", _) => "wolves".into(),
                ("person", _) => "people".into(),
                _ => format!("{label}s"),
            };
            format!("{count} {noun}")
        })
        .collect();
    let names = match parts.split_last() {
        Some((last, rest)) if !rest.is_empty() => format!("{} and {last}", rest.join(", ")),
        _ => parts.join(""),
    };
    format!("You notice the remains of {names} around you, the nearest {distance:.0} tiles {direction}.")
}

#[cfg(test)]
mod tests {
    use super::counted_line;

    #[test]
    fn counts_strangers_and_places_the_nearest() {
        assert_eq!(
            counted_line(&[("stranger", 12)], (2.4, "east")),
            "You notice the remains of 12 strangers around you, the nearest 2 tiles east."
        );
    }

    #[test]
    fn uses_species_plurals_in_group_order() {
        assert_eq!(counted_line(&[("stranger", 3), ("deer", 2), ("wolf", 2)], (4.0, "north")),
            "You notice the remains of 3 strangers, 2 deer and 2 wolves around you, the nearest 4 tiles north.");
        assert_eq!(
            counted_line(&[("wolf", 1), ("deer", 1)], (1.0, "west")),
            "You notice the remains of 1 wolf and 1 deer around you, the nearest 1 tiles west."
        );
    }
}
