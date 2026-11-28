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

/// One line: the person as compose reads it, and the words the generator wrote for it
/// (`living_rules::look::LookWords`, read by [`LookBook::words`]).
#[derive(Deserialize, Clone, Debug)]
pub struct Line {
    pub person: Person,
    #[serde(default)]
    pub words: serde_json::Value,
}

/// The client book (docs/LOOK.md §5, main `acfe1be4`; dev-box's final interface): its
/// generation, the lines under their keys, and the decor lines. No names, no person entries, no
/// pool, no swatches: a client cannot tell from a key who someone is, who else they are at
/// another age, or whether they were seeded.
#[derive(Deserialize, Default, Debug)]
#[serde(default)]
pub struct LookBook {
    /// The generation this book was written in (`world.look_book` names a world's), and every
    /// generation whose keys it holds, oldest first (char-4 is adding it; a book without it holds
    /// only its own).
    pub generation: String,
    pub generations: Vec<String>,
    pub lines: HashMap<String, Line>,
    /// Lines for background people only (`lk_…`), apart from every line a character can wear.
    pub decor: Vec<String>,
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

    /// Whether the book holds the keys of a world made with `generation`.
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
        // The authority's pick (`living_rules::look::pool_pick`), on the person's own seed.
        living_rules::look::pool_pick(seed, 0, fit.len()).map(|i| fit[i])
    }

    /// What a glance can say of the person wearing `key` (`living_rules::look::phrase`'s
    /// inputs): the line's words and its band by its type (an infant wears a child's type, and
    /// the far phrase says "child" for both). None for a key the book lacks or words that do not
    /// read.
    pub fn words(&self, key: &str) -> Option<(living_rules::look::LookWords, living_rules::look::LookBand)> {
        let line = self.lines.get(key)?;
        let words = serde_json::from_value(line.words.clone()).ok()?;
        let band = living_rules::look::LookBand::from_code(band_of_type(&line.person.kind)?)?;
        Some((words, band))
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

impl LookBook {
    /// The fewest lines (greedy) to draw beside `worn` so that every kind of mesh the book's
    /// files hold ([`mesh_kinds`]) is drawn at least once: a kind only some style files have
    /// makes pipelines of its own, compiled when the first person wearing one comes into sight
    /// unless the loading cover drew it (a braid's cloth, skinned and vertex-coloured with no UVs,
    /// cost 323 ms on a cold Metal cache when a battle's fighters arrived; pipeline-prewarm).
    /// Usually one line, often none.
    pub fn covering_kinds(&self, worn: &[String]) -> Vec<String> {
        let kinds = |l: &Line| -> BTreeSet<String> { l.person.files().iter().flat_map(|f| mesh_kinds(f)).collect() };
        let have: BTreeSet<String> = worn.iter().filter_map(|k| self.lines.get(k)).flat_map(kinds).collect();
        let want: Vec<(&str, BTreeSet<String>)> = self
            .lines
            .iter()
            .filter(|(k, l)| missing_file(k, &l.person).is_none())
            .map(|(k, l)| (k.as_str(), kinds(l).difference(&have).cloned().collect::<BTreeSet<String>>()))
            .filter(|(_, left)| !left.is_empty())
            .collect();
        cover(want)
    }
}

/// The kinds of mesh a glTF binary under the asset folder holds, by what gives a mesh pipelines
/// of its own: each primitive's vertex attributes, whether it has morph targets, and its
/// material's alpha mode and sidedness. Read from the file's JSON chunk once per file; empty for
/// a file that can't be read.
pub fn mesh_kinds(file: &str) -> BTreeSet<String> {
    static KINDS: OnceLock<Mutex<HashMap<String, BTreeSet<String>>>> = OnceLock::new();
    let cache = KINDS.get_or_init(Default::default);
    if let Some(k) = cache.lock().unwrap().get(file) {
        return k.clone();
    }
    let k = glb_json(&std::path::Path::new(&crate::lookdev::asset_root()).join(file)).map(|j| kinds_of(&j)).unwrap_or_default();
    cache.lock().unwrap().insert(file.to_string(), k.clone());
    k
}

/// A `.glb`'s JSON chunk.
fn glb_json(path: &std::path::Path) -> Option<serde_json::Value> {
    use std::io::Read;
    let mut f = std::fs::File::open(path).ok()?;
    let mut head = [0u8; 20];
    f.read_exact(&mut head).ok()?;
    if &head[0..4] != b"glTF" || &head[16..20] != b"JSON" {
        return None;
    }
    let mut json = vec![0u8; u32::from_le_bytes(head[12..16].try_into().ok()?) as usize];
    f.read_exact(&mut json).ok()?;
    serde_json::from_slice(&json).ok()
}

/// [`mesh_kinds`] of a glTF document.
fn kinds_of(j: &serde_json::Value) -> BTreeSet<String> {
    let materials = j["materials"].as_array().cloned().unwrap_or_default();
    let mut out = BTreeSet::new();
    for mesh in j["meshes"].as_array().into_iter().flatten() {
        for p in mesh["primitives"].as_array().into_iter().flatten() {
            let mut attrs: Vec<&str> = p["attributes"].as_object().map(|a| a.keys().map(|k| k.as_str()).collect()).unwrap_or_default();
            attrs.sort();
            let morphs = p["targets"].as_array().is_some_and(|t| !t.is_empty());
            let m = p["material"].as_u64().and_then(|i| materials.get(i as usize));
            let alpha = m.and_then(|m| m["alphaMode"].as_str()).unwrap_or("OPAQUE");
            let sides = m.and_then(|m| m["doubleSided"].as_bool()).unwrap_or(false);
            out.insert(format!("{}{} {alpha}{}", attrs.join("+"), if morphs { " morphs" } else { "" }, if sides { " double" } else { "" }));
        }
    }
    out
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

/// The book, read on first use; None (one warning) when there is none. `LIVING_GAME_LOOK_BOOK=<path>`
/// reads another (a test's copy: a line left out, another generation).
pub fn book() -> Option<&'static LookBook> {
    static BOOK: OnceLock<Option<LookBook>> = OnceLock::new();
    BOOK.get_or_init(|| {
        let path = std::env::var("LIVING_GAME_LOOK_BOOK").ok().filter(|p| !p.is_empty()).map(std::path::PathBuf::from).unwrap_or_else(|| std::path::Path::new(&crate::lookdev::asset_root()).join(FILE));
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
    // A hero drawn from their whole file needs nothing else (contract v1.3).
    let m = if compose::enabled() && compose::hero_file(p).is_some() { None } else { p.files().into_iter().find(|f| !root.join(f).exists()) };
    cache.lock().unwrap().insert(key.to_string(), m.clone());
    m
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A mesh's kind is its attributes, morphs, alpha mode and sidedness.
    #[test]
    fn mesh_kinds_tell_layouts_apart() {
        let j = serde_json::json!({
            "materials": [{ "alphaMode": "BLEND" }, {}],
            "meshes": [
                { "primitives": [{ "attributes": { "POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2 }, "material": 0, "targets": [{}] }] },
                { "primitives": [{ "attributes": { "NORMAL": 1, "POSITION": 0 }, "material": 1 }, { "attributes": { "POSITION": 0, "NORMAL": 1 } }] }
            ]
        });
        let k: Vec<String> = kinds_of(&j).into_iter().collect();
        assert_eq!(k, vec!["NORMAL+POSITION OPAQUE".to_string(), "NORMAL+POSITION+TEXCOORD_0 morphs BLEND".to_string()]);
    }

    fn line(kind: &str, hair: &str, outfit: &[&str]) -> serde_json::Value {
        serde_json::json!({ "person": { "type": kind, "height": 1.6, "styles": { "hair": hair, "outfit": outfit } }, "words": { "form": "woman", "girth": 2, "height": 1, "hair": "dark-haired", "top": "a green smock", "bottom": "dark trousers" } })
    }

    fn sample() -> LookBook {
        let text = serde_json::json!({
            "generation": "c4-test",
            "generations": ["c4-old", "c4-test"],
            "lines": {
                "lk_00000000000000a1": line("adult-f-a", "bob", &["jersey-f", "trousers-f"]),
                "lk_00000000000000a2": line("adult-f-a", "long", &["jersey-f"]),
                "lk_00000000000000c1": line("child-u-a", "bob", &["smock_50-f"]),
            },
            "decor": ["lk_00000000000000a2", "lk_00000000000000c1"],
        });
        LookBook::parse(&text.to_string()).unwrap()
    }

    #[test]
    fn a_book_reads_its_lines_and_generations() {
        let b = sample();
        assert_eq!(b.lines.len(), 3);
        assert!(b.knows("c4-test") && b.knows("c4-old") && !b.knows("c4-new"));
        assert!(LookBook::parse(r#"{"generation": "c4-b"}"#).unwrap().knows("c4-b"));
        assert_eq!(b.lines["lk_00000000000000c1"].person.kind, "child-u-a");
    }

    #[test]
    fn misses_say_why() {
        let b = sample();
        assert_eq!(b.recipe("").unwrap_err(), Miss::NoKey);
        assert_eq!(b.recipe("lk_ffffffffffffffff").unwrap_err(), Miss::Unknown("lk_ffffffffffffffff".into()));
        // A line whose type file is not on disk.
        let mut b = b;
        b.lines.insert("lk_00000000000000e1".into(), serde_json::from_value(line("no-such-type", "bob", &[])).unwrap());
        assert!(matches!(b.recipe("lk_00000000000000e1").unwrap_err(), Miss::NoFile(_, f) if f == "lookdev/types/no-such-type.glb"));
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
    fn a_keys_words_say_what_phrase_says() {
        let b = sample();
        let (w, band) = b.words("lk_00000000000000a1").unwrap();
        assert_eq!(band, living_rules::look::LookBand::Adult);
        assert_eq!(living_rules::look::phrase(&w, living_rules::look::LookSeen::Full, band), "a woman in a green smock and dark trousers, dark-haired, heavy-set");
        assert_eq!(living_rules::look::phrase(&w, living_rules::look::LookSeen::Far, band), "a woman in a green smock and dark trousers, heavy-set");
        assert!(b.words("lk_ffffffffffffffff").is_none());
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
