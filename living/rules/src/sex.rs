//! A person's body sex as a world fact (docs/LIVING_CORE.md, "Body sex"): female or male,
//! stored once per person on the authority (`sex`, private) and never changed. What follows
//! from it is in the rules: the words for a body by sex and life stage (`sex_words()`), the
//! world's pick for someone no seed decides (`female_share()`), kin words by sex
//! (`kin_terms()`), and whether starting a family needs a woman and a man
//! (`conceive_needs_pair()`). A look's `form` (`look::LookWords`) is how a line is drawn; a pool
//! entry's sex is read from its forms ([`of_form`]) so that people wear lines of their own sex.
//!
//! "Unknown" is the absence of a row (a world from before this change until `backfill_sex`):
//! every rule then behaves as it did before sex existed.

use crate::look::splitmix64;

/// A body's sex. The codes are what the authority's `sex` table stores.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Sex {
    Female,
    Male,
}

impl Sex {
    pub const ALL: [Sex; 2] = [Sex::Female, Sex::Male];

    /// 1 female, 2 male.
    pub fn code(self) -> u8 {
        match self {
            Sex::Female => 1,
            Sex::Male => 2,
        }
    }

    pub fn from_code(c: u8) -> Option<Self> {
        match c {
            1 => Some(Sex::Female),
            2 => Some(Sex::Male),
            _ => None,
        }
    }

    /// "female" or "male": the rules' names (the script's `actor.sex`, `my_sex`).
    pub fn name(self) -> &'static str {
        match self {
            Sex::Female => "female",
            Sex::Male => "male",
        }
    }

    /// "f", "female", "m" or "male" (any case): a seed's or a player's word. Nothing else.
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "f" | "female" => Some(Sex::Female),
            "m" | "male" => Some(Sex::Male),
            _ => None,
        }
    }
}

/// Mixed into the world seed for [`pick`], so the pick is independent of `look::pool_pick`'s
/// stream for the same id.
pub const SALT: u64 = 0x5E70_F00D_0B0D_1E55;

/// The world's pick for person `id` in a world of seed `world_seed` (births, newcomers, players
/// who do not choose, band members a seed leaves open): female when
/// `splitmix64((world_seed ^ SALT) ^ (id × 0x9E37_79B9_7F4A_7C15))` falls in the lowest
/// `female_share` of the u64 range. Deterministic; `female_share` is clamped to 0..1.
pub fn pick(world_seed: u64, id: u32, female_share: f32) -> Sex {
    let share = female_share.clamp(0.0, 1.0) as f64;
    let x = splitmix64((world_seed ^ SALT) ^ (id as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15));
    // The top 53 bits as a fraction in [0, 1).
    let u = (x >> 11) as f64 / (1u64 << 53) as f64;
    if u < share {
        Sex::Female
    } else {
        Sex::Male
    }
}

/// The sex a look line's `form` shows: "woman", "girl", "old woman" female; "man", "boy",
/// "old man" male; anything else ("baby", "") none.
pub fn of_form(form: &str) -> Option<Sex> {
    let f = form.trim().to_ascii_lowercase();
    let last = f.rsplit(' ').next().unwrap_or("");
    match last {
        "woman" | "girl" => Some(Sex::Female),
        "man" | "boy" => Some(Sex::Male),
        _ => None,
    }
}

/// The words for a body by sex and life stage (the world's `sex_words()`): what a self line, a
/// scene and a far figure say. Index = stage code (0 infant, 1 child, 2 adult, 3 elder).
#[derive(Clone, Debug, PartialEq)]
pub struct SexWords {
    pub female: [String; 4],
    pub male: [String; 4],
}

impl Default for SexWords {
    fn default() -> Self {
        let w = |a: [&str; 4]| a.map(String::from);
        Self { female: w(["baby girl", "girl", "woman", "old woman"]), male: w(["baby boy", "boy", "man", "old man"]) }
    }
}

impl SexWords {
    /// The word for `sex` at life stage `stage` (0..3; a later code reads as an elder).
    pub fn word(&self, sex: Sex, stage: u8) -> &str {
        let i = (stage as usize).min(3);
        match sex {
            Sex::Female => &self.female[i],
            Sex::Male => &self.male[i],
        }
    }
}

/// "a" or "an" before `word`.
pub fn article(word: &str) -> &'static str {
    if word.trim_start().starts_with(['a', 'e', 'i', 'o', 'u']) {
        "an"
    } else {
        "a"
    }
}

/// How often words about someone say she or he: (female, male) counts of the third-person
/// pronouns ("she", "her", "hers", "herself"; "he", "him", "his", "himself") and of sexed kin or
/// role words ("wife", "son", "mother", "widow"…) in `text`. What others wrote or remember of a
/// person, read for `backfill_sex` (a clear majority only) and for the seed check's warning on a
/// sheet whose words disagree with a resident's `sex`.
pub fn told(text: &str) -> (u32, u32) {
    const F: &[&str] = &["she", "her", "hers", "herself", "wife", "mother", "daughter", "sister", "grandmother", "granddaughter", "widow", "aunt", "niece", "woman", "girl", "mum", "mam", "ma", "gran", "granny", "nan"];
    const M: &[&str] = &["he", "him", "his", "himself", "husband", "father", "son", "brother", "grandfather", "grandson", "widower", "uncle", "nephew", "man", "boy", "dad", "da", "pa"];
    let t = text.to_lowercase();
    let (mut f, mut m) = (0, 0);
    for w in t.split(|c: char| !c.is_alphabetic()).filter(|w| !w.is_empty()) {
        if F.contains(&w) {
            f += 1;
        } else if M.contains(&w) {
            m += 1;
        }
    }
    (f, m)
}

/// The sex `(female, male)` counts clearly say: at least `min` words, and at least twice as
/// many one way as the other.
pub fn clear_majority((f, m): (u32, u32), min: u32) -> Option<Sex> {
    if f + m < min {
        None
    } else if f >= 2 * m.max(1) && f > m {
        Some(Sex::Female)
    } else if m >= 2 * f.max(1) && m > f {
        Some(Sex::Male)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codes_names_and_words_round_trip() {
        for s in Sex::ALL {
            assert_eq!(Sex::from_code(s.code()), Some(s));
            assert_eq!(Sex::parse(s.name()), Some(s));
        }
        assert_eq!(Sex::from_code(0), None);
        assert_eq!(Sex::parse("F"), Some(Sex::Female));
        assert_eq!(Sex::parse(" m "), Some(Sex::Male));
        for bad in ["", "x", "fm", "woman", "2"] {
            assert_eq!(Sex::parse(bad), None, "{bad}");
        }
        let w = SexWords::default();
        assert_eq!(w.word(Sex::Female, 2), "woman");
        assert_eq!(w.word(Sex::Male, 3), "old man");
        assert_eq!(w.word(Sex::Male, 9), "old man");
        assert_eq!(w.word(Sex::Female, 0), "baby girl");
    }

    #[test]
    fn forms_tell_a_line_s_sex() {
        for (f, s) in [("woman", Some(Sex::Female)), ("old woman", Some(Sex::Female)), ("girl", Some(Sex::Female)), ("man", Some(Sex::Male)), ("Old Man", Some(Sex::Male)), ("boy", Some(Sex::Male)), ("baby", None), ("", None), ("figure", None)] {
            assert_eq!(of_form(f), s, "{f}");
        }
    }

    /// The pick is deterministic, honours the share at its ends and is near it in between.
    #[test]
    fn the_world_s_pick_follows_its_share() {
        assert_eq!(pick(7, 3, 0.5), pick(7, 3, 0.5));
        assert!((1..500).all(|id| pick(42, id, 0.0) == Sex::Male));
        assert!((1..500).all(|id| pick(42, id, 1.0) == Sex::Female));
        for share in [0.25f32, 0.5, 0.8] {
            let n = 20_000u32;
            let f = (1..=n).filter(|id| pick(0xC0FFEE, *id, share) == Sex::Female).count() as f32 / n as f32;
            assert!((f - share).abs() < 0.02, "share {share}: {f}");
        }
        // Different worlds pick differently for the same id.
        let a: Vec<Sex> = (1..64).map(|id| pick(1, id, 0.5)).collect();
        let b: Vec<Sex> = (1..64).map(|id| pick(2, id, 0.5)).collect();
        assert_ne!(a, b);
    }

    #[test]
    fn what_others_say_is_counted() {
        assert_eq!(told("She keeps a quiet house and tends the sick; I rely on her."), (2, 0));
        assert_eq!(told("He is my captain, but he shamed me before Crane. My son."), (0, 3));
        assert_eq!(told("the shepherd's ledger"), (0, 0));
        assert_eq!(clear_majority((2, 0), 1), Some(Sex::Female));
        assert_eq!(clear_majority((1, 1), 1), None);
        assert_eq!(clear_majority((3, 1), 1), Some(Sex::Female));
        assert_eq!(clear_majority((3, 2), 1), None);
        assert_eq!(clear_majority((1, 4), 2), Some(Sex::Male));
        assert_eq!(clear_majority((1, 0), 2), None);
    }
}
