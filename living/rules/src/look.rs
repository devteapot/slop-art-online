//! A person's look (docs/LOOK.md): which look band a person is in, which pool entry an unseeded
//! person wears, when their band next changes, and the words anyone can say of what they see.
//!
//! Every function here is pure and shared: the authority calls them to write `look` rows, the
//! game client to label what it draws, and the mind service to word a scene. So a player and a
//! mind are told the same words from the same row.
//!
//! - **Bands** ([`look_band`]): infant (stage 0), child (stage 1, under `youth` years), youth
//!   (`youth` to under `adult` years, at stage 1 or 2), adult (stage 2, `adult` years or more) and
//!   elder (stage 3). The thresholds are the world's `look_bands()` law ([`LookBands`]); the age
//!   is `life::Life::years_old`, the years a scene states.
//! - **The pool** ([`pool_pick`]): someone the seed did not write (a birth, a newcomer, a player)
//!   wears the pool entry at `splitmix64(world_seed ^ (id × 0xD1B5_4A32_D192_ED03)) mod
//!   pool_len`, so the same world gives the same id the same look, and nothing is drawn.
//! - **The next change** ([`next_change`]): the age in years at which the band next changes, from
//!   the life table's stage ends and the bands' thresholds; `None` for an elder.
//! - **Words** ([`phrase`]): the generator's [`LookWords`] for the line, as much as the observer
//!   perceives ([`LookSeen`]): all of them once the person is made out, and beyond that only what
//!   is not face-scale on a player's screen at that range (no sex, hair or beard).

use crate::life::{Life, Stage};
use serde::Deserialize;

/// A look band: which of a person's lines they wear. Its code is the `band` column of `look` and
/// `look_line`, and the key of a seed's `looks.people` entries ("0".."4" or the names).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum LookBand {
    Infant = 0,
    Child = 1,
    Youth = 2,
    Adult = 3,
    Elder = 4,
}

impl LookBand {
    pub const ALL: [LookBand; 5] = [LookBand::Infant, LookBand::Child, LookBand::Youth, LookBand::Adult, LookBand::Elder];

    pub fn code(self) -> u8 {
        self as u8
    }

    pub fn from_code(c: u8) -> Option<Self> {
        Self::ALL.get(c as usize).copied()
    }

    pub fn name(self) -> &'static str {
        match self {
            LookBand::Infant => "infant",
            LookBand::Child => "child",
            LookBand::Youth => "youth",
            LookBand::Adult => "adult",
            LookBand::Elder => "elder",
        }
    }

    /// A band as a seed writes it: its code ("3") or its name ("adult").
    pub fn parse(s: &str) -> Option<Self> {
        Self::ALL.iter().copied().find(|b| b.name() == s || b.code().to_string() == s)
    }
}

/// The world's `look_bands()` law: the ages in years at which youth and adulthood begin.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LookBands {
    pub youth: f32,
    pub adult: f32,
}

impl Default for LookBands {
    fn default() -> Self {
        Self { youth: 12.0, adult: 18.0 }
    }
}

/// The band of a person at life stage `stage` (0 infant, 1 child, 2 adult, 3 elder: the
/// `character.stage` codes) and `age_years` years old. A grown person (stage 2) under the adult
/// age is a youth, as is a child (stage 1) at or past the youth age; a world whose childhood
/// outlasts the adult age keeps such a child a youth.
pub fn look_band(stage: u8, age_years: f32, b: &LookBands) -> LookBand {
    match stage {
        0 => LookBand::Infant,
        1 if age_years < b.youth => LookBand::Child,
        1 => LookBand::Youth,
        3 => LookBand::Elder,
        _ if age_years < b.adult => LookBand::Youth,
        _ => LookBand::Adult,
    }
}

/// The `character.stage` code of a life stage.
pub fn stage_code(s: Stage) -> u8 {
    match s {
        Stage::Infant => 0,
        Stage::Child => 1,
        Stage::Adult => 2,
        Stage::Elder => 3,
    }
}

/// The life stage at `age_years` under a life table (stage ends are fractions of `life.years`),
/// compared in years, so the age [`next_change`] names for a stage end is in the new stage.
fn stage_at_years(life: &Life, age_years: f32) -> u8 {
    stage_code(if age_years < life.infant * life.years {
        Stage::Infant
    } else if age_years < life.child * life.years {
        Stage::Child
    } else if age_years < life.elder * life.years {
        Stage::Adult
    } else {
        Stage::Elder
    })
}

/// The band of someone `age_years` old under a life table: [`look_band`] at the stage the table
/// gives that age.
pub fn band_at(life: &Life, age_years: f32, b: &LookBands) -> LookBand {
    look_band(stage_at_years(life, age_years), age_years, b)
}

/// The age in years at which someone `age_years` old next changes band, under the life table
/// `life` (its stage ends: `infant`, `child` and `elder` × `years`) and the bands' thresholds:
/// the first of those ages past `age_years` at which [`band_at`] differs from now. `None` once
/// no change is left (an elder). A caller turns it into world time with `life::days_of_years`.
pub fn next_change(life: &Life, age_years: f32, b: &LookBands) -> Option<f32> {
    let now = band_at(life, age_years, b);
    let mut at = [life.infant * life.years, life.child * life.years, life.elder * life.years, b.youth, b.adult];
    at.sort_by(|x, y| x.total_cmp(y));
    at.into_iter().filter(|t| *t > age_years).find(|t| band_at(life, *t, b) != now)
}

/// The SplitMix64 output function (Steele, Lea and Flood 2014): the state is used as given.
pub fn splitmix64(x: u64) -> u64 {
    let mut z = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// Which pool entry character `id` wears in a world of seed `world_seed`:
/// `splitmix64(world_seed ^ (id × 0xD1B5_4A32_D192_ED03)) mod pool_len` (wrapping multiply);
/// `None` for an empty pool. Two people may draw the same entry and look alike, like twins.
pub fn pool_pick(world_seed: u64, id: u32, pool_len: usize) -> Option<usize> {
    if pool_len == 0 {
        return None;
    }
    Some((splitmix64(world_seed ^ (id as u64).wrapping_mul(0xD1B5_4A32_D192_ED03)) % pool_len as u64) as usize)
}

/// How much of a person's look an observer perceives (the `perceived_of` law's `look`). The
/// line's key reaches a player's client whenever the person is seen; this decides only how much
/// a mind is told: everything once made out (`Full`), beyond that (`Far`) no hair or beard.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub enum LookSeen {
    #[default]
    Full,
    Far,
    None,
}

/// Whom a mind's scene describes by look: the world's `appearance_in_scene()` law.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum AppearanceInScene {
    /// Strangers and figures too far away to make out (shipped).
    #[default]
    Unnamed,
    /// Everyone in the scene.
    All,
    /// No one.
    None,
}

impl AppearanceInScene {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "unnamed" => Some(Self::Unnamed),
            "all" => Some(Self::All),
            "none" => Some(Self::None),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Unnamed => "unnamed",
            Self::All => "all",
            Self::None => "none",
        }
    }
}

/// The words the generator wrote for a line (docs/LOOK.md §2): what a glance can say. `form` is
/// appearance only: no rule reads it. Empty words are left out of a phrase.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LookWords {
    /// "woman", "man", "girl", "boy", "baby", "old woman".
    #[serde(default)]
    pub form: String,
    /// 0 slight, 1 medium, 2 heavy-set.
    #[serde(default = "middling")]
    pub girth: u8,
    /// 0 short, 1 middling, 2 tall (for the band).
    #[serde(default = "middling")]
    pub height: u8,
    /// "dark-haired", "grey-haired", "bald", "" (covered).
    #[serde(default)]
    pub hair: String,
    /// "a green smock".
    #[serde(default)]
    pub top: String,
    /// "dark trousers".
    #[serde(default)]
    pub bottom: String,
    /// "a cap", "a kerchief", "".
    #[serde(default)]
    pub head: String,
    /// "a white beard", "stubble", "".
    #[serde(default)]
    pub beard: String,
}

fn middling() -> u8 {
    1
}

impl Default for LookWords {
    /// No words, of middling height and girth.
    fn default() -> Self {
        Self { form: String::new(), girth: 1, height: 1, hair: String::new(), top: String::new(), bottom: String::new(), head: String::new(), beard: String::new() }
    }
}

impl LookWords {
    /// What is wrong with the words, if anything: girth and height are 0, 1 or 2.
    pub fn problem(&self) -> Option<String> {
        if self.girth > 2 || self.height > 2 {
            return Some(format!("girth and height are 0, 1 or 2 (girth {}, height {})", self.girth, self.height));
        }
        None
    }
}

fn article(word: &str) -> &'static str {
    if word.starts_with(['a', 'e', 'i', 'o', 'u']) {
        "an"
    } else {
        "a"
    }
}

/// What an observer can say of a person's look: `words` for the line they wear, `seen` as the
/// `perceived_of` law grants it, `band` their look band.
///
/// - `Full`: "a woman in a green smock and dark trousers, dark-haired, heavy-set, in a kerchief"
///   (a tall or short person is "a tall woman ..."; a beard is "with a white beard").
/// - `Far`: the body's form by sex when the line's `form` shows one ("woman", "old man": a far
///   figure is drawn in full on a player's screen, and its build and clothes show its sex; body-sex,
///   2026-11-13), else the silhouette by band ("child" for an infant or a child, "old figure" for
///   an elder, else "figure"); height and girth, the garments and the headwear: "a tall woman in a
///   green smock and dark trousers, in a kerchief". No hair or beard (face-scale at that range).
/// - `None`: "".
pub fn phrase(words: &LookWords, seen: LookSeen, band: LookBand) -> String {
    let noun = match seen {
        LookSeen::None => return String::new(),
        LookSeen::Full if !words.form.trim().is_empty() => words.form.trim().to_string(),
        LookSeen::Full => "person".into(),
        LookSeen::Far if crate::sex::of_form(&words.form).is_some() => words.form.trim().to_string(),
        LookSeen::Far => match band {
            LookBand::Infant | LookBand::Child => "child".into(),
            LookBand::Elder => "old figure".into(),
            _ => "figure".into(),
        },
    };
    let tall = match words.height {
        0 => "short ",
        2 => "tall ",
        _ => "",
    };
    let head = format!("{tall}{noun}");
    let mut s = format!("{} {head}", article(&head));
    let clothes: Vec<&str> = [words.top.trim(), words.bottom.trim()].into_iter().filter(|w| !w.is_empty()).collect();
    if !clothes.is_empty() {
        s.push_str(" in ");
        s.push_str(&clothes.join(" and "));
    }
    let full = seen == LookSeen::Full;
    if full && !words.hair.trim().is_empty() {
        s.push_str(", ");
        s.push_str(words.hair.trim());
    }
    match words.girth {
        0 => s.push_str(", slight"),
        2 => s.push_str(", heavy-set"),
        _ => {}
    }
    if !words.head.trim().is_empty() {
        s.push_str(", in ");
        s.push_str(words.head.trim());
    }
    if full && !words.beard.trim().is_empty() {
        s.push_str(", with ");
        s.push_str(words.beard.trim());
    }
    s
}

/// Whether `key` is a line key: `lk_` and 16 lowercase hex digits.
pub fn is_line_key(key: &str) -> bool {
    is_key(key, "lk_")
}

/// Whether `key` is a person key: `lp_` and 16 lowercase hex digits.
pub fn is_person_key(key: &str) -> bool {
    is_key(key, "lp_")
}

fn is_key(key: &str, prefix: &str) -> bool {
    key.strip_prefix(prefix).is_some_and(|h| h.len() == 16 && h.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn person() -> Life {
        // species.json's person table.
        Life { years: 70.0, infant: 0.03, child: 0.23, elder: 0.85, old_age: 0.87, ..Life::default() }
    }

    #[test]
    fn bands_follow_stage_and_age() {
        let b = LookBands::default();
        assert_eq!(look_band(0, 1.0, &b), LookBand::Infant);
        assert_eq!(look_band(1, 6.0, &b), LookBand::Child);
        assert_eq!(look_band(1, 11.99, &b), LookBand::Child);
        assert_eq!(look_band(1, 12.0, &b), LookBand::Youth);
        assert_eq!(look_band(2, 16.5, &b), LookBand::Youth);
        assert_eq!(look_band(2, 18.0, &b), LookBand::Adult);
        assert_eq!(look_band(2, 40.0, &b), LookBand::Adult);
        assert_eq!(look_band(3, 60.0, &b), LookBand::Elder);
        // An infant is an infant at any age, an elder an elder.
        assert_eq!(look_band(0, 14.0, &b), LookBand::Infant);
        assert_eq!(look_band(3, 10.0, &b), LookBand::Elder);
        // A world's thresholds.
        let late = LookBands { youth: 14.0, adult: 21.0 };
        assert_eq!(look_band(1, 13.0, &late), LookBand::Child);
        assert_eq!(look_band(2, 20.0, &late), LookBand::Youth);
        for b in LookBand::ALL {
            assert_eq!(LookBand::from_code(b.code()), Some(b));
            assert_eq!(LookBand::parse(b.name()), Some(b));
            assert_eq!(LookBand::parse(&b.code().to_string()), Some(b));
        }
        assert_eq!(LookBand::from_code(5), None);
        assert_eq!(LookBand::parse("teen"), None);
    }

    #[test]
    fn the_next_change_is_the_first_age_where_the_band_moves() {
        let (l, b) = (person(), LookBands::default());
        // Stage 1 starts at 2.1 years, youth at 12, stage 2 at 16.1 (still a youth), adult at 18,
        // elder at 59.5.
        let at = |age: f32| next_change(&l, age, &b);
        assert!((at(0.5).unwrap() - 2.1).abs() < 1e-3, "{:?}", at(0.5));
        assert_eq!(at(5.0), Some(12.0));
        assert_eq!(at(12.0), Some(18.0), "16.1 is a stage change but not a band change");
        assert_eq!(at(15.0), Some(18.0));
        assert!((at(30.0).unwrap() - 59.5).abs() < 1e-3);
        assert_eq!(at(60.0), None);
        // Walking a life from birth gives each band once, in order.
        let mut age = 0.0;
        let mut seen = vec![band_at(&l, age, &b)];
        while let Some(t) = next_change(&l, age, &b) {
            assert!(t > age);
            age = t;
            seen.push(band_at(&l, age, &b));
        }
        assert_eq!(seen, LookBand::ALL.to_vec());
        // A short-lived world: adulthood (stage 2) before the youth age skips the youth band.
        let short = Life { years: 10.0, ..person() };
        assert_eq!(band_at(&short, 3.0, &b), LookBand::Youth, "a grown 3-year-old under 18 is a youth");
    }

    #[test]
    fn the_pool_pick_is_a_stated_mix() {
        assert_eq!(pool_pick(7, 1, 0), None);
        // Vectors for the client, the Spark and char-4 (splitmix64 of seed ^ id × 0xD1B54A32D192ED03).
        assert_eq!(splitmix64(0), 0xE220_A839_7B1D_CDAF);
        assert_eq!(pool_pick(0, 0, 1_000_000), Some((0xE220_A839_7B1D_CDAFu64 % 1_000_000) as usize));
        for (seed, id, len) in [(3u64, 1u32, 128usize), (3, 2, 128), (42, 77, 64), (u64::MAX, u32::MAX, 5)] {
            let want = (splitmix64(seed ^ (id as u64).wrapping_mul(0xD1B5_4A32_D192_ED03)) % len as u64) as usize;
            assert_eq!(pool_pick(seed, id, len), Some(want));
        }
        // Spread: 128 entries over 10,000 ids, each drawn.
        let mut n = [0u32; 128];
        for id in 1..=10_000 {
            n[pool_pick(3, id, 128).unwrap()] += 1;
        }
        assert!(n.iter().all(|c| (40..=120).contains(c)), "{n:?}");
        // Another world draws otherwise.
        assert!((1..100).any(|id| pool_pick(3, id, 128) != pool_pick(4, id, 128)));
    }

    #[test]
    fn phrases_say_what_is_perceived() {
        let w = LookWords { form: "woman".into(), girth: 2, height: 1, hair: "dark-haired".into(), top: "a green smock".into(), bottom: "dark trousers".into(), head: "a kerchief".into(), beard: String::new() };
        assert_eq!(phrase(&w, LookSeen::Full, LookBand::Adult), "a woman in a green smock and dark trousers, dark-haired, heavy-set, in a kerchief");
        let tall = LookWords { height: 2, ..w.clone() };
        assert_eq!(phrase(&tall, LookSeen::Far, LookBand::Adult), "a tall woman in a green smock and dark trousers, heavy-set, in a kerchief");
        assert_eq!(phrase(&w, LookSeen::None, LookBand::Adult), "");
        let man = LookWords { form: "old man".into(), girth: 0, height: 0, hair: "grey-haired".into(), top: "a brown coat".into(), bottom: String::new(), head: String::new(), beard: "a white beard".into() };
        assert_eq!(phrase(&man, LookSeen::Full, LookBand::Elder), "a short old man in a brown coat, grey-haired, slight, with a white beard");
        let far = phrase(&man, LookSeen::Far, LookBand::Elder);
        // A far figure's form says its sex (body-sex): the screen draws it in full.
        assert_eq!(far, "a short old man in a brown coat, slight");
        for hidden in ["grey", "beard"] {
            assert!(!far.contains(hidden), "{far}");
        }
        let baby = LookWords { form: "baby".into(), ..LookWords::default() };
        assert_eq!(phrase(&baby, LookSeen::Full, LookBand::Infant), "a baby");
        assert_eq!(phrase(&baby, LookSeen::Far, LookBand::Infant), "a child");
        assert_eq!(phrase(&LookWords::default(), LookSeen::Full, LookBand::Adult), "a person");
        let elder = LookWords { form: "old woman".into(), ..LookWords::default() };
        assert_eq!(phrase(&elder, LookSeen::Full, LookBand::Elder), "an old woman");
    }

    #[test]
    fn keys_and_words_are_checked() {
        assert!(is_line_key("lk_0123456789abcdef"));
        assert!(!is_line_key("lk_0123456789ABCDEF"));
        assert!(!is_line_key("lk_0123456789abcde"));
        assert!(!is_line_key("lp_0123456789abcdef"));
        assert!(is_person_key("lp_00000000000000ff"));
        let w: LookWords = serde_json::from_str(r#"{"form":"girl","girth":0,"height":2,"top":"a grey shift"}"#).unwrap();
        assert_eq!((w.girth, w.height, w.problem()), (0, 2, None));
        assert!(serde_json::from_str::<LookWords>(r#"{"form":"girl","colour":"green"}"#).is_err(), "LookWords has no colour");
        assert!(LookWords { girth: 3, ..w }.problem().is_some());
    }
}
