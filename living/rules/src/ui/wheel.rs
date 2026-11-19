//! The wheel (docs/INTERFACE.md §8): up to eight sections round a hub, for the acts on one
//! target, where the world's `menus()` asks for one. Hold F, move toward a section, let go.
//!
//! This module has what is shared and pure: the vocabulary (`Dir`, `Section`), a `menus()` row
//! as read ([`MenuSpec`]), and the layout ([`wheel_of`]). Reading `menus()` is
//! `living_rules::script`'s (`Scripts::menus`, `Scripts::menu_for`); drawing and input are the
//! game client's. The sections are the F list's own acts, built on the same checks, so a wheel
//! offers nothing the list could not and sends nothing a mind could not write.

use super::On;

vocab! {
    /// A direction on a wheel, clockwise from north.
    Dir, DIRS { N = "n", Ne = "ne", E = "e", Se = "se", S = "s", Sw = "sw", W = "w", Nw = "nw" }
}

vocab! {
    /// The client's own sections, beside the rules' skills: the list's Talk, Their window and
    /// Introduce yourself rows (a person's), and More (the full list).
    Section, SECTIONS { Talk = "talk", Window = "window", Introduce = "introduce", More = "more" }
}

/// The keys of a `menus()` row.
pub const MENU_TRAITS: &[&str] = &["on", "kinds", "choose", "wheel", "fill"];

/// The places a `menus()` row may attach to: those whose list F or C opens.
pub const MENU_PLACES: &[On] = &[On::Person, On::Thing, On::Me];

impl Dir {
    /// Its index clockwise from north (0..8), the section's number less one.
    pub fn index(self) -> usize {
        Dir::ALL.iter().position(|d| *d == self).unwrap_or(0)
    }

    /// The direction at an index clockwise from north (wrapping).
    pub fn at(i: usize) -> Dir {
        Dir::ALL[i % 8]
    }

    /// Its angle in degrees, clockwise from north (screen up).
    pub fn degrees(self) -> f32 {
        self.index() as f32 * 45.0
    }
}

/// What a section is: one of the rules' skills, or one of the client's own sections.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Pin {
    Skill(String),
    Own(Section),
}

impl Pin {
    /// A section's name as `menus()` spells it: a skill's name, or the client section's.
    pub fn parse(s: &str) -> Pin {
        match Section::parse(s) {
            Some(o) => Pin::Own(o),
            None => Pin::Skill(s.to_string()),
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Pin::Skill(s) => s,
            Pin::Own(o) => o.as_str(),
        }
    }
}

/// One row of `menus()`: which place and target kinds it covers, whether they get a wheel, and
/// what it pins where.
#[derive(Clone, Debug, PartialEq)]
pub struct MenuSpec {
    pub on: On,
    /// The target kinds it covers (empty: every target at that place).
    pub kinds: Vec<String>,
    pub choose: super::Choose,
    /// The section pinned at each direction, by [`Dir::index`].
    pub wheel: [Option<Pin>; 8],
    /// Whether the acts it does not pin fill its free directions (default true).
    pub fill: bool,
}

impl MenuSpec {
    /// Whether the row covers a target of this kind at this place.
    pub fn covers(&self, on: On, kind: &str) -> bool {
        self.on == on && (self.kinds.is_empty() || self.kinds.iter().any(|k| k == kind))
    }

    /// The direction a section is pinned at.
    pub fn pinned(&self, what: &Pin) -> Option<Dir> {
        self.wheel.iter().position(|p| p.as_ref() == Some(what)).map(Dir::at)
    }
}

/// A section the list could have toward this target: a skill (or a client section), whether the
/// client's check allows it now, and whether choosing it opens a further choice (an item, a
/// want, a topic: `›`) or the text box (`…`).
#[derive(Clone, Debug, PartialEq)]
pub struct Candidate {
    pub what: Pin,
    pub allowed: bool,
    pub sub: bool,
    pub words: bool,
}

/// A section as laid out.
#[derive(Clone, Debug, PartialEq)]
pub struct WheelSection {
    pub dir: Dir,
    pub what: Pin,
    /// Allowed by the client's check now. A greyed section is a hint: choosing it still sends
    /// the act, and the authority decides.
    pub allowed: bool,
    /// Pinned by `menus()` (keeps its direction whatever the rules allow now).
    pub pinned: bool,
    pub sub: bool,
    pub words: bool,
}

/// A laid-out wheel: its sections by direction, and what is behind More (in the list's order).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Wheel {
    pub sections: Vec<WheelSection>,
    pub more: Vec<Pin>,
}

impl Wheel {
    pub fn at(&self, d: Dir) -> Option<&WheelSection> {
        self.sections.iter().find(|s| s.dir == d)
    }
}

/// Lay out a wheel (docs/INTERFACE.md §8.1, "What goes where"):
/// 1. pinned sections take their directions (a pinned act the client does not offer now greys
///    in place; it is never removed, so a direction learned once keeps working);
/// 2. with `fill`, the other acts the rules allow now take the free directions clockwise from
///    north, in the list's order (`cands` is in the list's order);
/// 3. whatever is left goes behind More, which takes its pinned direction, else the first free
///    one clockwise from south (kept free for it before filling).
///
/// A filled act shows only while allowed, as the list does: the checks cannot tell "never here"
/// from "not now". More appears only when something is behind it, or when it is pinned.
pub fn wheel_of(spec: &MenuSpec, cands: &[Candidate]) -> Wheel {
    let mut w = Wheel::default();
    let mut used = [false; 8];
    let found = |p: &Pin| cands.iter().find(|c| &c.what == p);
    for (i, p) in spec.wheel.iter().enumerate() {
        let Some(p) = p else { continue };
        used[i] = true;
        let c = found(p);
        // More is always there when pinned; a client section is offered when its candidate is.
        let allowed = matches!(p, Pin::Own(Section::More)) || c.is_some_and(|c| c.allowed);
        w.sections.push(WheelSection { dir: Dir::at(i), what: p.clone(), allowed, pinned: true, sub: c.is_some_and(|c| c.sub), words: c.is_some_and(|c| c.words) });
    }
    let more_pinned = spec.pinned(&Pin::Own(Section::More)).is_some();
    let rest: Vec<&Candidate> = cands.iter().filter(|c| c.allowed && spec.pinned(&c.what).is_none() && c.what != Pin::Own(Section::More)).collect();
    let free: Vec<usize> = (0..8).filter(|i| !used[*i]).collect();
    // More's direction, kept free before filling when it will be needed and is not pinned.
    let fits = spec.fill && rest.len() <= free.len();
    let more_at = if !more_pinned && !rest.is_empty() && !fits { (0..8).map(|k| (4 + k) % 8).find(|i| !used[*i]) } else { None };
    if let Some(i) = more_at {
        used[i] = true;
    }
    let mut left: Vec<Pin> = Vec::new();
    for c in rest {
        let slot = if spec.fill { (0..8).find(|i| !used[*i]) } else { None };
        match slot {
            Some(i) => {
                used[i] = true;
                w.sections.push(WheelSection { dir: Dir::at(i), what: c.what.clone(), allowed: true, pinned: false, sub: c.sub, words: c.words });
            }
            None => left.push(c.what.clone()),
        }
    }
    if let Some(i) = more_at {
        w.sections.push(WheelSection { dir: Dir::at(i), what: Pin::Own(Section::More), allowed: true, pinned: false, sub: true, words: false });
    }
    w.more = left;
    w.sections.sort_by_key(|s| s.dir.index());
    w
}
