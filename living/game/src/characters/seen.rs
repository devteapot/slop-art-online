//! What the authority projects of a person's look (docs/LOOK.md §2): the `look` column appended
//! to `seen_characters` (a line key, `lk_…`, sent to whoever sees the person at every distance)
//! and the world's `look_book` generation, read in one place so the rest of the client never
//! touches the row.
//!
//! **Until the authority half lands** the bindings have no such columns, and these read a
//! test-only shim instead: `LIVING_GAME_LOOK_SHIM=on[;none=ID,…][;missing=ID,…]
//! [;generation=G][;grow=ID@S]`, or `old` (a world made before looks: no keys, no generation), gives each person a line the book lets characters wear, of the
//! age band of their life stage, by their id; no key to the ids in `none`; a key the book lacks
//! to those in `missing`; the world the generation `G` (default: the book's); and person `ID` a
//! line of the next band `S` seconds after the first look is read (`grow`). Unset, every person
//! has no key and is drawn as before. The shim goes with the rebase onto the authority's
//! bindings.

use super::book::{self, LookBook};
use living_bindings::SeenCharacter;
use std::sync::OnceLock;

/// A person's look as this viewer perceives it.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Seen {
    /// `lk_…`, or empty: no key (a world from before looks, or not a person).
    pub look: String,
}

/// The columns of a person's row.
pub fn of(c: &SeenCharacter) -> Seen {
    match shim() {
        Some(s) => s.of(c, book::book()),
        None => Seen::default(),
    }
}

/// The world's look generation (`world.look_book`): empty for a world from before looks.
pub fn world_generation() -> String {
    shim().map(|s| s.generation.clone()).unwrap_or_default()
}

/// The book's verdict on the world's generation: the warning to give once at connect, if any.
pub fn generation_warning(world: &str, book: Option<&LookBook>) -> Option<String> {
    let b = book?;
    (!world.is_empty() && !b.knows(world)).then(|| format!("looks: the world was made with look generation {world}, which the look book ({}) does not hold; people it lacks are drawn as VRoid bases", b.generation))
}

/// The age band a life stage gives when the age within it is not known: the shim's, and nothing
/// else's (the authority sends the key).
fn band_of_stage(stage: u8) -> u8 {
    match stage {
        0 | 1 => 1,
        3 => 4,
        _ => 3,
    }
}

struct Shim {
    none: Vec<u32>,
    missing: Vec<u32>,
    generation: String,
    grow: Option<(u32, f32)>,
    old: bool,
    start: std::time::Instant,
}

fn shim() -> Option<&'static Shim> {
    static SHIM: OnceLock<Option<Shim>> = OnceLock::new();
    SHIM.get_or_init(|| {
        let v = std::env::var("LIVING_GAME_LOOK_SHIM").ok().filter(|v| !v.is_empty())?;
        let mut s = Shim { none: vec![], missing: vec![], generation: String::new(), grow: None, old: false, start: std::time::Instant::now() };
        for part in v.split(';').map(str::trim) {
            match part.split_once('=') {
                Some(("none", n)) => s.none = n.split(',').filter_map(|x| x.trim().parse().ok()).collect(),
                Some(("missing", n)) => s.missing = n.split(',').filter_map(|x| x.trim().parse().ok()).collect(),
                Some(("generation", g)) => s.generation = g.to_string(),
                Some(("grow", g)) => s.grow = g.split_once('@').and_then(|(id, t)| Some((id.parse().ok()?, t.parse().ok()?))),
                None if part == "old" => s.old = true,
                _ => {}
            }
        }
        if s.generation.is_empty() && !s.old {
            s.generation = book::book().map(|b| b.generation.clone()).unwrap_or_default();
        }
        bevy::log::warn!("looks: test shim on ({v}): look columns are made up on the client");
        Some(s)
    })
    .as_ref()
}

impl Shim {
    fn of(&self, c: &SeenCharacter, book: Option<&LookBook>) -> Seen {
        if c.kind != "person" || self.old || self.none.contains(&c.id) {
            return Seen::default();
        }
        if self.missing.contains(&c.id) {
            return Seen { look: "lk_ffffffffffffffff".into() };
        }
        let mut band = band_of_stage(c.stage);
        if self.grow.is_some_and(|(id, t)| id == c.id && self.start.elapsed().as_secs_f32() >= t) {
            band = (band + 1).min(4);
        }
        let Some(b) = book else { return Seen::default() };
        let fit: Vec<&str> = b.wearable().into_iter().filter(|(_, l)| book::band_of_type(&l.person.kind) == Some(band)).map(|(k, _)| k).collect();
        let look = (!fit.is_empty()).then(|| fit[(c.id as u64).wrapping_mul(2_654_435_761) as usize % fit.len()].to_string()).unwrap_or_default();
        Seen { look }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_world_from_another_generation_warns_once_at_connect() {
        let b = LookBook::parse(r#"{"generation": "c4-b", "generations": ["c4-a"]}"#).unwrap();
        assert!(generation_warning("c4-b", Some(&b)).is_none());
        assert!(generation_warning("c4-a", Some(&b)).is_none());
        assert!(generation_warning("", Some(&b)).is_none());
        assert!(generation_warning("c4-c", Some(&b)).is_some_and(|w| w.contains("c4-c")));
        assert!(generation_warning("c4-c", None).is_none());
    }
}
