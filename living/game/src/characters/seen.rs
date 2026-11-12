//! What the authority projects of a person's look (docs/LOOK.md §2): the columns appended to
//! `seen_characters` (`look`, `look_band`, `girth`, `height`, `colour`) and the world's
//! `look_book` generation, read in one place so the rest of the client never touches the row.
//!
//! **Until the authority half lands** the bindings have no such columns, and these read a
//! test-only shim instead: `LIVING_GAME_LOOK_SHIM=pool[;none=N][;missing=N][;generation=G]
//! [;grow=ID@S]` gives each person a pool entry by their id at the band of their life stage,
//! no key to every id with `id % N == 0` (`none`), a key the book lacks to every id with
//! `id % N == 1` (`missing`), the world the generation `G`, and person `ID` the next band `S`
//! seconds after the first look is read (`grow`). Unset, every person has no key and is drawn
//! as before. The shim goes with the rebase onto the authority's bindings.

use super::book::{self, LookBook};
use living_bindings::SeenCharacter;
use std::sync::OnceLock;

/// A person's look as this viewer perceives it.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Seen {
    /// `lk_…`, or empty: no key (a world from before looks; or a far row, if the authority sends
    /// none there).
    pub look: String,
    /// The look band (`book::INFANT`..`book::ELDER`); 255 for what is not a person.
    pub band: u8,
    pub girth: u8,
    pub height: u8,
    /// The dominant colour word.
    pub colour: String,
}

/// The columns of a person's row.
pub fn of(c: &SeenCharacter) -> Seen {
    match shim() {
        Some(s) => s.of(c, book::book()),
        None => Seen { band: 255, girth: 255, height: 255, ..Default::default() },
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

/// The band a life stage gives when the age within it is not known: the shim's, and nothing
/// else's (the authority sends the band).
fn band_of_stage(stage: u8) -> u8 {
    match stage {
        0 => book::INFANT,
        1 => book::CHILD,
        3 => book::ELDER,
        _ => book::ADULT,
    }
}

struct Shim {
    none: Option<u32>,
    missing: Option<u32>,
    generation: String,
    grow: Option<(u32, f32)>,
    start: std::time::Instant,
}

fn shim() -> Option<&'static Shim> {
    static SHIM: OnceLock<Option<Shim>> = OnceLock::new();
    SHIM.get_or_init(|| {
        let v = std::env::var("LIVING_GAME_LOOK_SHIM").ok().filter(|v| !v.is_empty())?;
        let mut s = Shim { none: None, missing: None, generation: String::new(), grow: None, start: std::time::Instant::now() };
        for part in v.split(';').map(str::trim) {
            match part.split_once('=') {
                Some(("none", n)) => s.none = n.parse().ok().filter(|n| *n > 0),
                Some(("missing", n)) => s.missing = n.parse().ok().filter(|n| *n > 1),
                Some(("generation", g)) => s.generation = g.to_string(),
                Some(("grow", g)) => s.grow = g.split_once('@').and_then(|(id, t)| Some((id.parse().ok()?, t.parse().ok()?))),
                _ => {}
            }
        }
        if s.generation.is_empty() {
            s.generation = book::book().map(|b| b.generation.clone()).unwrap_or_default();
        }
        bevy::log::warn!("looks: test shim on ({v}): look columns are made up on the client");
        Some(s)
    })
    .as_ref()
}

impl Shim {
    fn of(&self, c: &SeenCharacter, book: Option<&LookBook>) -> Seen {
        if c.kind != "person" {
            return Seen { band: 255, girth: 255, height: 255, ..Default::default() };
        }
        let mut band = band_of_stage(c.stage);
        if self.grow.is_some_and(|(id, t)| id == c.id && self.start.elapsed().as_secs_f32() >= t) {
            band = (band + 1).min(book::ELDER);
        }
        let look = match book {
            _ if self.none.is_some_and(|n| c.id % n == 0) => String::new(),
            _ if self.missing.is_some_and(|n| c.id % n == 1) => "lk_ffffffffffffffff".into(),
            Some(b) if !b.pool.is_empty() => {
                let entry = &b.pool[(c.id as usize).wrapping_mul(2_654_435_761) % b.pool.len()];
                b.people.get(entry).and_then(|bands| bands.get(&band.to_string()).or_else(|| bands.values().last())).cloned().unwrap_or_default()
            }
            _ => String::new(),
        };
        Seen { look, band, girth: 1, height: 1, colour: String::new() }
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
