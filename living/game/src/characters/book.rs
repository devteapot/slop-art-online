//! The look book (docs/LOOK.md §5): every person line a released world can name, under opaque
//! keys, shipped with the client as `assets/characters/looks.json` (git-ignored, from char-4's
//! bundle).
//!
//! **What the authority sends** (`seen_characters`, per viewer): a person's line key (`look`,
//! `lk_` and 16 hex digits), their look band, and girth, height and colour words. The client
//! draws the line it finds under the key ([`LookBook::recipe`]); the key says nothing by itself.
//! A person without a key, a key the book does not hold, or a line whose type or style files are
//! not on disk is drawn as before this change: a VRoid recipe from the land seed and their id
//! (`live::recipe_for`), with one warning line.
//!
//! **Background people** (an island's extras, who have no authority rows) take lines from
//! `decor`, a pool kept apart from the newcomers' `pool`, by their own seed ([`LookBook::decor`]),
//! so an extra is never a real newcomer's twin.
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

/// Look bands (docs/LOOK.md §4), as `seen_characters.look_band` carries them; 255 is not a person.
pub const INFANT: u8 = 0;
pub const CHILD: u8 = 1;
#[allow(dead_code)]
pub const YOUTH: u8 = 2;
pub const ADULT: u8 = 3;
pub const ELDER: u8 = 4;

/// One line: the person as compose reads it, and the words the generator wrote for it (kept as
/// the book has them; `living_rules::look::phrase` reads them once the authority half lands).
#[derive(Deserialize, Clone, Debug)]
pub struct Line {
    pub person: Person,
    #[serde(default)]
    #[allow(dead_code)]
    pub words: serde_json::Value,
}

#[derive(Deserialize, Default, Debug)]
#[serde(default)]
pub struct LookBook {
    /// The generation this book was written in, and earlier ones it still holds every key of
    /// (the book is append-only while a released world uses a key).
    pub generation: String,
    pub generations: Vec<String>,
    pub lines: HashMap<String, Line>,
    /// Person entries newcomers and births are drawn from (`lp_…`), and the background pool.
    pub pool: Vec<String>,
    pub decor: Vec<String>,
    /// A person entry's line for each band (`"3"` → `lk_…`).
    pub people: HashMap<String, BTreeMap<String, String>>,
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
            Miss::NoKey => "looks: people without a look key are drawn as VRoid bases (a world from before looks)".into(),
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

    /// A background person's line by their seed: a `decor` entry at `band` (else the entry's
    /// nearest band). None without a decor pool.
    pub fn decor(&self, seed: u64, band: u8) -> Option<(&str, &Line)> {
        if self.decor.is_empty() {
            return None;
        }
        let entry = &self.decor[(mix(seed) % self.decor.len() as u64) as usize];
        let bands = self.people.get(entry)?;
        let key = bands.get(&band.to_string()).or_else(|| bands.iter().min_by_key(|(b, _)| b.parse::<i32>().map_or(99, |b| (b - band as i32).abs())).map(|(_, k)| k))?;
        self.lines.get_key_value(key.as_str()).map(|(k, l)| (k.as_str(), l))
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
                bevy::log::info!("looks: {} lines, {} pool and {} decor people, generation {}", b.lines.len(), b.pool.len(), b.decor.len(), b.generation);
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
            "pool": ["lp_0000000000000001"],
            "decor": ["lp_0000000000000002"],
            "people": { "lp_0000000000000002": { "1": "lk_00000000000000c1", "3": "lk_00000000000000a2" } },
        });
        LookBook::parse(&text.to_string()).unwrap()
    }

    #[test]
    fn a_book_reads_its_lines_and_generations() {
        let b = sample();
        assert_eq!(b.lines.len(), 3);
        assert!(b.knows("c4-test") && b.knows("c4-old") && !b.knows("c4-new"));
        assert_eq!(b.lines["lk_00000000000000c1"].person.kind, "child-u-a");
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
    fn a_background_person_keeps_one_decor_entry_across_bands() {
        let b = sample();
        assert_eq!(b.decor(7, CHILD).map(|(k, _)| k), Some("lk_00000000000000c1"));
        assert_eq!(b.decor(7, ADULT).map(|(k, _)| k), Some("lk_00000000000000a2"));
        // No line for the band: the entry's nearest.
        assert_eq!(b.decor(7, ELDER).map(|(k, _)| k), Some("lk_00000000000000a2"));
        assert!(LookBook::default().decor(7, ADULT).is_none());
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
