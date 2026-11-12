//! The look book (docs/LOOK.md §5): every person line a released world can name, under opaque
//! keys, shipped with the client as `assets/characters/looks.json` (git-ignored, from char-4's
//! bundle).
//!
//! **What the authority sends** (`seen_characters`, per viewer): a person's line key (`look`,
//! `lk_` and 16 hex digits, a hash of the drawn fields), to whoever sees them, at every distance.
//! The client draws the line it finds under the key ([`LookBook::recipe`]); the key says nothing
//! by itself, and the book holds only lines (no names, no people across bands, no pool).
//! A person without a key, a key the book does not hold, or a line whose type or style files are
//! not on disk is drawn as before this change: a VRoid recipe from the land seed and their id
//! (`live::recipe_for`), with one warning line.
//!
//! **Background people** (an island's extras, who have no authority rows) take lines from
//! `decor`, a list kept apart from every line a character can wear, by their own seed
//! ([`LookBook::decor`]), so an extra is never a real person's twin.
//!
//! **Loaded once, lazily** ([`book`]): the first person drawn reads it; a missing or broken file
//! is one warning, and then everyone is drawn as before.

use super::compose::{self, Person};
use super::Recipe;
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::{Mutex, OnceLock};

/// The book's path under the asset folder.
pub const FILE: &str = "characters/looks.json";

/// A line's age band by its type (`child-u-a`, `youth-f-b`, `adult-m-c`, `elder-f-a`): 1 child,
/// 2 youth, 3 adult, 4 elder (docs/LOOK.md §4's bands; infants wear child types). None for a type
/// outside them.
pub fn band_of_type(kind: &str) -> Option<u8> {
    match kind.split('-').next()? {
        "child" => Some(1),
        "youth" => Some(2),
        "adult" => Some(3),
        "elder" => Some(4),
        _ => None,
    }
}

/// One line: the person as compose reads it, and the words the generator wrote for it (kept as
/// the book has them; `living_rules::look::phrase` reads them once the authority half lands).
#[derive(Deserialize, Clone, Debug)]
pub struct Line {
    pub person: Person,
    #[serde(default)]
    #[allow(dead_code)]
    pub words: serde_json::Value,
}

/// The client book (docs/LOOK.md §5, as settled with dev-box 2026-11-12): its generations, the
/// lines under their keys, the colour words' swatches, each outfit style's slot and layer, and
/// the decor lines. No names, no person entries, no pool: a client cannot tell from a key who
/// someone is, who else they are at another age, or whether they were seeded.
#[derive(Deserialize, Default, Debug)]
#[serde(default)]
pub struct LookBook {
    /// The generation this book was written in, and the generations it holds every key of
    /// (the book is append-only while a released world uses a key).
    pub generation: String,
    pub generations: Vec<String>,
    pub lines: HashMap<String, Line>,
    /// A colour word's swatch (`"green"` → `#5d7f4a`).
    pub swatches: HashMap<String, String>,
    /// Each outfit style's part of the body and layer (`"smock_58-f"` → upper, 2), for the
    /// chips (`looks.rs`).
    pub outfit: HashMap<String, Piece>,
    /// Lines for background people only (`lk_…`), apart from every line a character can wear.
    pub decor: Vec<String>,
}

/// Where an outfit style is worn: `slot` (`upper`, `lower`, or another a chip does not show)
/// and `layer` (higher is worn over lower).
#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Piece {
    pub slot: String,
    #[serde(default)]
    pub layer: i32,
}

/// Why a person is not drawn from the book.
#[derive(Debug, Clone, PartialEq)]
pub enum Miss {
    /// No book on disk (or it did not parse).
    NoBook,
    /// A person with no key: a world from before looks, or a row that carries none.
    NoKey,
    /// A key this book does not hold (another generation).
    Unknown(String),
    /// The line names a file that is not on disk.
    NoFile(String, String),
}

impl Miss {
    /// The one warning line for it.
    pub fn warning(&self) -> String {
        match self {
            Miss::NoBook => format!("looks: no look book at {FILE}; people are drawn as VRoid bases"),
            Miss::NoKey => "looks: people without a look key in a world with looks are drawn as VRoid bases".into(),
            Miss::Unknown(k) => format!("looks: {k} is not in the look book; drawn as a VRoid base"),
            Miss::NoFile(k, f) => format!("looks: {k} wears {f}, which is not on disk; drawn as a VRoid base"),
        }
    }
}

impl LookBook {
    pub fn parse(text: &str) -> Result<LookBook, String> {
        serde_json::from_str(text).map_err(|e| e.to_string())
    }

    /// Whether the book holds every key of a world made with `generation`.
    pub fn knows(&self, generation: &str) -> bool {
        generation == self.generation || self.generations.iter().any(|g| g == generation)
    }

    /// The recipe a key draws: the line composed from its type and style files, checked on disk
    /// (once a key).
    pub fn recipe(&self, key: &str) -> Result<Recipe, Miss> {
        if key.is_empty() {
            return Err(Miss::NoKey);
        }
        let line = self.lines.get(key).ok_or_else(|| Miss::Unknown(key.to_string()))?;
        if let Some(f) = missing_file(key, &line.person) {
            return Err(Miss::NoFile(key.to_string(), f));
        }
        Ok(from_line(key, &line.person))
    }

    /// A background person's line by their seed: one of the `decor` lines whose type is grown
    /// (youth, adult or elder; a child's when `grown` is false). None without one.
    pub fn decor(&self, seed: u64, grown: bool) -> Option<(&str, &Line)> {
        let mut fit: Vec<(&str, &Line)> = self.decor.iter().filter_map(|k| self.lines.get_key_value(k.as_str())).filter(|(_, l)| band_of_type(&l.person.kind).is_some_and(|b| (b >= 2) == grown)).map(|(k, l)| (k.as_str(), l)).collect();
        if fit.is_empty() {
            return None;
        }
        fit.sort_by(|a, b| a.0.cmp(b.0));
        Some(fit[(mix(seed) % fit.len() as u64) as usize])
    }

    /// The lines a character can wear (every line but the decor), in key order.
    pub fn wearable(&self) -> Vec<(&str, &Line)> {
        let mut v: Vec<(&str, &Line)> = self.lines.iter().filter(|(k, _)| !self.decor.contains(k)).map(|(k, l)| (k.as_str(), l)).collect();
        v.sort_by(|a, b| a.0.cmp(b.0));
        v
    }

    /// The fewest lines (greedy) that between them wear every type and every style file of the
    /// lines named by `keys` (every line when empty): what the loading cover draws so their
    /// pipelines exist before anyone is seen in them (`loading.rs`). Lines with files missing on
    /// disk are left out.
    pub fn covering(&self, keys: &[String]) -> Vec<String> {
        let want: Vec<(&str, BTreeSet<String>)> = self
            .lines
            .iter()
            .filter(|(k, _)| keys.is_empty() || keys.contains(k))
            .filter(|(k, l)| missing_file(k, &l.person).is_none())
            .map(|(k, l)| (k.as_str(), l.person.files().into_iter().collect()))
            .collect();
        cover(want)
    }
}

/// Greedy set cover: each step the line that wears the most files not yet worn (ties by key).
fn cover(mut want: Vec<(&str, BTreeSet<String>)>) -> Vec<String> {
    want.sort_by(|a, b| a.0.cmp(b.0));
    let mut left: BTreeSet<String> = want.iter().flat_map(|(_, f)| f.iter().cloned()).collect();
    let mut out = Vec::new();
    while let Some((k, files)) = want.iter().max_by_key(|(k, f)| (f.intersection(&left).count(), std::cmp::Reverse(*k))) {
        if files.intersection(&left).next().is_none() {
            break;
        }
        for f in files {
            left.remove(f);
        }
        out.push(k.to_string());
    }
    out
}

/// The book, read on first use; None (one warning) when there is none.
pub fn book() -> Option<&'static LookBook> {
    static BOOK: OnceLock<Option<LookBook>> = OnceLock::new();
    BOOK.get_or_init(|| {
        let path = std::path::Path::new(&crate::lookdev::asset_root()).join(FILE);
        match std::fs::read_to_string(&path).map_err(|e| e.to_string()).and_then(|s| LookBook::parse(&s)) {
            Ok(b) => {
                bevy::log::info!("looks: {} lines ({} decor), generation {}", b.lines.len(), b.decor.len(), b.generation);
                Some(b)
            }
            Err(e) => {
                bevy::log::warn!("looks: {}: {e}; people are drawn as VRoid bases", path.display());
                None
            }
        }
    })
    .as_ref()
}

/// The world's look generation (`world.look_book`) once connected: empty for a world made before
/// looks, whose people are drawn as VRoid bases without a warning each.
pub fn set_world(generation: Option<String>) {
    *WORLD.lock().unwrap() = generation;
}

/// The connected world's look generation (None while not connected).
pub fn world() -> Option<String> {
    WORLD.lock().unwrap().clone()
}

static WORLD: Mutex<Option<String>> = Mutex::new(None);

/// Each miss's warning once a session.
pub fn warn_once(miss: &Miss) {
    static SEEN: OnceLock<Mutex<BTreeSet<String>>> = OnceLock::new();
    let w = miss.warning();
    if SEEN.get_or_init(Default::default).lock().unwrap().insert(w.clone()) {
        bevy::log::warn!("{w}");
    }
}

/// A key's recipe: the line on its type's file, at the line's own height (`compose::prepare`
/// takes the rest from the line).
fn from_line(key: &str, p: &Person) -> Recipe {
    Recipe {
        name: key.to_string(),
        base: format!("{}/{}.glb", compose::TYPES, p.kind),
        height: p.height,
        proportions: p.proportions.clone(),
        colors: p.colors.clone(),
        outfit: BTreeMap::new(),
        identity: p.identity.clone(),
        person: Some(p.clone()),
    }
}

/// The first file a key's line names that is not on disk (checked once a key).
fn missing_file(key: &str, p: &Person) -> Option<String> {
    static CHECKED: OnceLock<Mutex<HashMap<String, Option<String>>>> = OnceLock::new();
    let cache = CHECKED.get_or_init(Default::default);
    if let Some(m) = cache.lock().unwrap().get(key) {
        return m.clone();
    }
    let root = std::path::PathBuf::from(crate::lookdev::asset_root());
    let m = p.files().into_iter().find(|f| !root.join(f).exists());
    cache.lock().unwrap().insert(key.to_string(), m.clone());
    m
}

/// SplitMix64's finaliser: a background person's seed spread over the decor pool.
fn mix(seed: u64) -> u64 {
    let mut z = seed.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line(kind: &str, hair: &str, outfit: &[&str]) -> serde_json::Value {
        serde_json::json!({ "person": { "type": kind, "height": 1.6, "styles": { "hair": hair, "outfit": outfit } }, "words": { "colour": "green" } })
    }

    fn sample() -> LookBook {
        let text = serde_json::json!({
            "generation": "c4-test",
            "generations": ["c4-old"],
            "lines": {
                "lk_00000000000000a1": line("adult-f-a", "bob", &["jersey-f", "trousers-f"]),
                "lk_00000000000000a2": line("adult-f-a", "long", &["jersey-f"]),
                "lk_00000000000000c1": line("child-u-a", "bob", &["smock_50-f"]),
            },
            "decor": ["lk_00000000000000a2", "lk_00000000000000c1"],
            "swatches": { "green": "#5d7f4a" },
            "outfit": { "jersey-f": { "slot": "upper", "layer": 1 }, "trousers-f": { "slot": "lower", "layer": 1 } },
        });
        LookBook::parse(&text.to_string()).unwrap()
    }

    #[test]
    fn a_book_reads_its_lines_and_generations() {
        let b = sample();
        assert_eq!(b.lines.len(), 3);
        assert!(b.knows("c4-test") && b.knows("c4-old") && !b.knows("c4-new"));
        assert_eq!(b.lines["lk_00000000000000c1"].person.kind, "child-u-a");
        assert_eq!(b.swatches["green"], "#5d7f4a");
        assert_eq!(b.outfit["trousers-f"], Piece { slot: "lower".into(), layer: 1 });
    }

    #[test]
    fn misses_say_why() {
        let b = sample();
        assert_eq!(b.recipe("").unwrap_err(), Miss::NoKey);
        assert_eq!(b.recipe("lk_ffffffffffffffff").unwrap_err(), Miss::Unknown("lk_ffffffffffffffff".into()));
        // The test has no asset folder, so every line's type file is missing.
        assert!(matches!(b.recipe("lk_00000000000000a1").unwrap_err(), Miss::NoFile(_, f) if f == "lookdev/types/adult-f-a.glb"));
    }

    #[test]
    fn background_people_wear_decor_lines_only() {
        let b = sample();
        assert_eq!(b.decor(7, true).map(|(k, _)| k), Some("lk_00000000000000a2"));
        assert_eq!(b.decor(7, false).map(|(k, _)| k), Some("lk_00000000000000c1"));
        assert!(LookBook::default().decor(7, true).is_none());
        // A character never wears a decor line.
        assert_eq!(b.wearable().iter().map(|(k, _)| *k).collect::<Vec<_>>(), vec!["lk_00000000000000a1"]);
        assert_eq!((band_of_type("youth-f-b"), band_of_type("elder-m-a"), band_of_type("giant")), (Some(2), Some(4), None));
    }

    #[test]
    fn the_cover_wears_every_file_with_few_lines() {
        let set = |fs: &[&str]| fs.iter().map(|f| f.to_string()).collect::<BTreeSet<_>>();
        let want = vec![("a", set(&["t1", "h1", "o1"])), ("b", set(&["t1", "h1"])), ("c", set(&["t2", "h2", "o1"])), ("d", set(&["t2"]))];
        assert_eq!(cover(want), vec!["a".to_string(), "c".to_string()]);
        assert!(cover(vec![]).is_empty());
    }

    #[test]
    fn a_line_draws_at_its_own_height_on_its_type() {
        let b = sample();
        let r = from_line("lk_00000000000000a1", &b.lines["lk_00000000000000a1"].person);
        assert_eq!(r.base, "lookdev/types/adult-f-a.glb");
        assert_eq!(r.height, 1.6);
        assert!(r.person.is_some());
    }
}
