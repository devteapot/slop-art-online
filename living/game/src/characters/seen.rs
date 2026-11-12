//! What the authority projects of a person's look (docs/LOOK.md §2, §7): `seen_characters.look`,
//! the line key (`lk_…`) of the line the person wears now, for anyone this viewer sees at any
//! distance, its own character included ("" for animals and for a person without a look row),
//! and `world.look_book`, the generation the world wears. Read in one place, so the rest of the
//! client never touches the row.

use super::book::LookBook;
use living_bindings::{DbConnection, SeenCharacter, WorldTableAccess};
use spacetimedb_sdk::Table;

/// A person's look as this viewer perceives it.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Seen {
    /// `lk_…`, or empty: no key (a world from before looks, or not a person).
    pub look: String,
}

/// The columns of a person's row.
pub fn of(c: &SeenCharacter) -> Seen {
    Seen { look: c.look.clone() }
}

/// The world's look generation (`world.look_book`): empty for a world made before looks.
pub fn world_generation(conn: &DbConnection) -> String {
    conn.db.world().iter().next().map(|w| w.look_book).unwrap_or_default()
}

/// The book's verdict on the world's generation: the warning to give once at connect, if any.
pub fn generation_warning(world: &str, book: Option<&LookBook>) -> Option<String> {
    let b = book?;
    (!world.is_empty() && !b.knows(world)).then(|| format!("looks: the world was made with look generation {world}, which the look book ({}) does not hold; people it lacks are drawn as VRoid bases", b.generation))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_world_from_another_generation_warns_once_at_connect() {
        let b = LookBook::parse(r#"{"generation": "c4-b", "generations": ["c4-a", "c4-b"]}"#).unwrap();
        assert!(generation_warning("c4-b", Some(&b)).is_none());
        assert!(generation_warning("c4-a", Some(&b)).is_none());
        assert!(generation_warning("", Some(&b)).is_none());
        assert!(generation_warning("c4-c", Some(&b)).is_some_and(|w| w.contains("c4-c")));
        assert!(generation_warning("c4-c", None).is_none());
    }
}
