//! Reading interface declarations (`<name>_ui()`, docs/INTERFACE.md §3) into
//! [`crate::ui::UiSpec`], once, when the script compiles.
//!
//! Lenient here, strict at install: every problem goes into `ui_errors` and the field it is in
//! falls back to its default, so a client that compiles a newer world's script keeps every rule
//! and the rest of each declaration. `Scripts::validate`, which only the authority's install
//! calls, refuses a script with any `ui_errors`, naming the function and the accepted keys.

use super::{ActorFacts, Scripts, SkillCtx};
use crate::combat::MissileSpec;
use crate::ui::{self, BarPlace, Look, On, Pick, Running, UiSpec, WayUi};
use rhai::{Array, Dynamic, Map, Scope};
use std::collections::BTreeMap;

/// What compiling the declarations gives the script: every skill's presentation, in the
/// script's order, the problems found, and the missiles the defaults were derived from.
#[derive(Clone, Debug, Default)]
pub(super) struct UiRead {
    pub specs: BTreeMap<String, UiSpec>,
    pub order: Vec<String>,
    pub errors: Vec<String>,
    pub missiles: BTreeMap<String, MissileSpec>,
}

/// A text, or a list of texts given as one text or a list.
fn texts(f: &str, k: &str, v: &Dynamic) -> Result<Vec<String>, String> {
    if let Ok(s) = v.clone().into_string() {
        return Ok(vec![s]);
    }
    let a = v.clone().try_cast::<Array>().ok_or_else(|| format!("{f}: `{k}` is a name or a list of names"))?;
    a.into_iter().map(|x| x.into_string().map_err(|_| format!("{f}: `{k}` is a name or a list of names"))).collect()
}

fn text(f: &str, k: &str, v: &Dynamic) -> Result<String, String> {
    v.clone().into_string().map_err(|_| format!("{f}: `{k}` must be a text"))
}

/// A name from a closed vocabulary.
fn one_of<T>(f: &str, k: &str, v: &Dynamic, parse: fn(&str) -> Option<T>, names: &[&str]) -> Result<T, String> {
    let s = text(f, k, v)?;
    parse(&s).ok_or_else(|| format!("{f}: `{k}` is one of {} (not `{s}`)", names.join(", ")))
}

fn named(f: &str, k: &str, s: &str, list: &'static [&'static str]) -> Result<&'static str, String> {
    ui::name_in(list, s).ok_or_else(|| if list.is_empty() { format!("{f}: `{k}` names nothing yet: the world has no such names (not `{s}`)") } else { format!("{f}: `{k}` is one of {} (not `{s}`)", list.join(", ")) })
}

/// A map's keys must all be known.
fn keys_of(f: &str, what: &str, m: &Map, known: &[&str]) -> Vec<String> {
    m.keys().filter(|k| !known.contains(&k.as_str())).map(|k| format!("{f}: unknown {what} `{k}` ({what}s are {})", known.join(", "))).collect()
}

impl Scripts {
    /// A newcomer person's missile for a skill, as `skill_card` has it.
    fn newcomer_missile(&self, skill: &str) -> Option<MissileSpec> {
        let shape = self.shapes.get(skill).filter(|s| s.missile)?;
        let c = SkillCtx { actor: ActorFacts { kind: "person".into(), ..Default::default() }, skill: skill.to_string(), qty: shape.hold_ms, ..Default::default() };
        self.missile(skill, &c).ok()
    }

    fn ui_source<'a>(&'a self, name: &'a str, missiles: &BTreeMap<String, MissileSpec>) -> ui::Source<'a> {
        ui::Source {
            name,
            spec: self.skills.get(name),
            shape: self.shapes.get(name),
            missile: missiles.get(name).copied(),
            on_bar: self.shapes.on_bar(name),
            checked: self.has(&format!("{name}_check")),
            shows: self.shows.get(name).map(|s| s.look.as_str()),
        }
    }

    /// Read every skill's presentation: its defaults, and its `<name>_ui()` over them.
    pub(super) fn read_ui(&self) -> UiRead {
        let mut r = UiRead::default();
        for s in self.shapes.names() {
            if let Some(m) = self.newcomer_missile(s) {
                r.missiles.insert(s.to_string(), m);
            }
        }
        // Skills in the script's order, then combat skills that declare no spec, by name.
        let mut names: Vec<String> = self.skills.names().map(String::from).collect();
        names.extend(self.shapes.names().filter(|n| self.skills.get(n).is_none()).map(String::from));
        for n in &names {
            r.specs.insert(n.clone(), ui::defaults(&self.ui_source(n, &r.missiles)));
        }
        // Declarations: functions of no parameter named `<name>_ui`, in the script's order.
        let mut decls: Vec<&String> = self.nullary.iter().filter(|f| f.ends_with("_ui") && f.len() > 3).collect();
        let at = |f: &str| self.source.rfind(&format!("fn {f}(")).unwrap_or(usize::MAX);
        decls.sort_by_cached_key(|f| (at(f), (*f).clone()));
        for f in decls {
            let Some(name) = f.strip_suffix("_ui") else { continue };
            let skill = self.skills.get(name).is_some() || self.shapes.get(name).is_some();
            let way = self.has(&format!("{name}_speech"));
            if skill && way {
                r.errors.push(format!("{f}: `{name}` is both a skill and a way of speaking; rename one"));
                continue;
            }
            if !skill && !way {
                r.errors.push(format!("{f}: `{name}` is not a skill (no `{name}_spec()`) nor a way of speaking (no `{name}_speech()`): a declaration only presents what the rules have"));
                continue;
            }
            let m = match self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, f, ()).map_err(|e| format!("{f}: {e}")).and_then(|d| d.try_cast::<Map>().ok_or_else(|| format!("{f} must return a map"))) {
                Ok(m) => m,
                Err(e) => {
                    r.errors.push(e);
                    continue;
                }
            };
            let base = if way { UiSpec { on: vec![On::Box], way: Some(WayUi::default()), ..ui::defaults(&ui::Source { name, spec: None, shape: None, missile: None, on_bar: false, checked: false, shows: None }) } } else { r.specs[name].clone() };
            let spec = self.declared(f, name, way, &m, base, &mut r.errors);
            if !names.iter().any(|n| n == name) {
                names.push(name.to_string());
            }
            r.specs.insert(name.to_string(), spec);
        }
        // A single bar place claimed twice: the first claim in the script's order keeps it.
        let mut claimed: BTreeMap<(BarPlace, i64), String> = BTreeMap::new();
        for n in &names {
            let Some(u) = r.specs.get_mut(n) else { continue };
            let Some(p) = u.place else { continue };
            let key = match p {
                BarPlace::Skill => match u.order {
                    Some(o) => (p, o),
                    None => continue,
                },
                p if p.single() => (p, 0),
                _ => continue,
            };
            if let Some(first) = claimed.get(&key) {
                r.errors.push(format!("{n}_ui: the bar place `{}`{} is already `{first}`'s", p.as_str(), if p == BarPlace::Skill { format!(" (order {})", key.1) } else { String::new() }));
                u.place = None;
                u.order = None;
            } else {
                claimed.insert(key, n.clone());
            }
        }
        r.order = names;
        r
    }

    /// One declaration over its defaults. Each field that is wrong keeps its default.
    fn declared(&self, f: &str, name: &str, way: bool, m: &Map, mut u: UiSpec, errors: &mut Vec<String>) -> UiSpec {
        u.declared = true;
        let spec = self.skills.get(name);
        let shape = self.shapes.get(name);
        errors.extend(keys_of(f, "trait", m, ui::UI_TRAITS));
        let mut err = |e: String| errors.push(e);
        macro_rules! field {
            ($k:literal, $parse:expr) => {
                if let Some(v) = m.get($k) {
                    match $parse(v) {
                        Ok(x) => Some(x),
                        Err(e) => {
                            err(e);
                            None
                        }
                    }
                } else {
                    None
                }
            };
        }
        if !way {
            for k in ui::WAY_UI_TRAITS.iter().filter(|k| m.contains_key(**k)) {
                err(format!("{f}: `{k}` is for a way of speaking; `{name}` is a skill"));
            }
        } else {
            for k in ["label", "order"].iter().filter(|k| m.contains_key(**k)) {
                err(format!("{f}: a way's `{k}` is set by `{name}_speech()`, not by its `_ui()`"));
            }
        }
        if !way {
            if let Some(l) = field!("label", |v| text(f, "label", v)) {
                if l.trim().is_empty() {
                    err(format!("{f}: `label` is a short display name, not empty"));
                } else {
                    u.label = l;
                }
            }
            let most = ui::MOST_SKILL_KEYS as i64;
            if let Some(o) = field!("order", |v: &Dynamic| v.as_int().ok().filter(|o| (0..most).contains(o)).ok_or_else(|| format!("{f}: `order` is a whole number 0..{most}"))) {
                u.order = Some(o);
            }
        }
        // Where it attaches.
        if let Some(list) = field!("on", |v| texts(f, "on", v)) {
            let mut on = Vec::new();
            let mut ok = true;
            for s in list {
                let Some(p) = On::parse(&s) else {
                    err(format!("{f}: `on` names places among {} (not `{s}`)", ui::PLACES.join(", ")));
                    ok = false;
                    continue;
                };
                let why = match p {
                    On::Box if !way => Some("a skill is not in the text box; `box` is for ways of speaking".to_string()),
                    _ if way && p != On::Box => Some(format!("a way of speaking is in the text box (`box`), not `{s}`")),
                    On::Person | On::Thing | On::Offer if !spec.is_some_and(|k| k.needs_target) => Some(format!("`{s}` needs a spec with `target: true`")),
                    // A point is a target only to a skill whose rules aim it at one.
                    On::Ground if !shape.is_some_and(|s| s.aim == crate::combat::Aim::Point) => Some("`ground` needs a combat aim of `point` (a skill that takes a point)".to_string()),
                    // Toward oneself a skill that needs a target sends an act the grammar refuses.
                    On::Me if spec.is_some_and(|k| k.needs_target) => Some(format!("`self` sends no target, and `{name}_spec()` needs one")),
                    On::Item if !spec.is_some_and(|k| k.needs_item) => Some("`item` needs a spec with `item`".to_string()),
                    On::Bar if shape.is_some() && !self.shapes.on_bar(name) => Some(format!("`{name}` is a combat skill: on the bar it must be in `skill_bar()`")),
                    _ => None,
                };
                match why {
                    Some(w) => {
                        err(format!("{f}: `on`: {w}"));
                        ok = false;
                    }
                    None if !on.contains(&p) => on.push(p),
                    None => {}
                }
            }
            // A presentation may move a skill, not take it from players only.
            if ok && on.is_empty() && !u.on.is_empty() {
                err(format!("{f}: `on` is empty, which would take `{name}` from players while minds keep it; to hide a skill from both, its spec says `listed: false`"));
                ok = false;
            }
            if ok {
                u.on = on;
            }
        }
        if let Some(p) = field!("place", |v| one_of(f, "place", v, BarPlace::parse, ui::BAR_PLACES)) {
            if u.is_on(On::Bar) {
                u.place = Some(p);
            } else {
                err(format!("{f}: `place` is a place on the bar, and `{name}` is not on it (`on` has no `bar`)"));
            }
        }
        // The input is checked against the rest once every field is read.
        let input = field!("input", |v| one_of(f, "input", v, ui::Input::parse, ui::INPUTS));
        if let Some(list) = field!("picks", |v| texts(f, "picks", v)) {
            let mut picks = Vec::new();
            let mut ok = true;
            for s in list {
                match Pick::parse(&s) {
                    None => {
                        err(format!("{f}: `picks` names choices among {} (not `{s}`)", ui::PICKS.join(", ")));
                        ok = false;
                    }
                    Some(p) if !spec.is_some_and(|k| p.fits(k)) => {
                        err(format!("{f}: `picks: {s}` needs {}", p.needs()));
                        ok = false;
                    }
                    Some(p) if !picks.contains(&p) => picks.push(p),
                    Some(_) => {}
                }
            }
            if ok {
                u.picks = picks;
            }
        }
        if let Some(c) = field!("choose", |v| one_of(f, "choose", v, ui::Choose::parse, ui::CHOOSE)) {
            u.choose = c;
        }
        if let Some(src) = field!("source", |v| one_of(f, "source", v, ui::ItemSource::parse, ui::SOURCES)) {
            use ui::ItemSource as S;
            let why = match (src, spec) {
                (_, None) => Some(format!("`{name}` has no spec")),
                (_, Some(k)) if !k.needs_item => Some(format!("`{name}_spec()` takes no item")),
                (S::SpecItems, Some(k)) if k.items.is_empty() => Some(format!("`{name}_spec()` lists no `items`")),
                (S::Products, Some(_)) if self.products_of(name).is_empty() => Some(format!("`{name}` makes nothing here (no `{name}_making()`, or no recipe of it in `recipes()`)")),
                (S::TargetHolds, Some(k)) if !k.needs_target => Some(format!("`{name}_spec()` takes no target")),
                _ => None,
            };
            match why {
                Some(w) => err(format!("{f}: `source: {}`: {w}", src.as_str())),
                None => u.source = Some(src),
            }
        }
        if let Some(d) = field!("detail", |v| text(f, "detail", v)) {
            match self.detail_errors(f, &d, name, u.source, spec) {
                Some(e) => err(e),
                None => u.detail = Some(d),
            }
        }
        if field!("unready", |v| one_of(f, "unready", v, ui::Unready::parse, ui::UNREADY)).is_some() {
            // What a press does while a stance is not met needs a stance, and no combat shape has
            // one yet (the Spark's drawn state).
            err(format!("{f}: `unready` needs a combat `stance` on `{name}_combat()`, and the rules have none yet"));
        }
        if let Some(s) = field!("toggles", |v| text(f, "toggles", v).and_then(|s| named(f, "toggles", &s, ui::STATES))) {
            u.toggles = Some(s);
        }
        if let Some(d) = field!("drag", |v| text(f, "drag", v)) {
            match On::parse(&d).filter(|p| matches!(p, On::Person | On::Thing)) {
                None => err(format!("{f}: `drag` is `person` or `thing` (not `{d}`)")),
                Some(_) if !spec.is_some_and(|k| k.needs_target && k.needs_item) => err(format!("{f}: `drag` drops an item on a target: it needs a spec with `target: true` and `item`")),
                Some(p) => u.drag = Some(p),
            }
        }
        if let Some(p) = field!("pin", |v: &Dynamic| v.as_bool().map_err(|_| format!("{f}: `pin` must be true or false"))) {
            if p && !u.is_on(On::Person) {
                err(format!("{f}: `pin` shows a button in the person window: `on` must have `person`"));
            } else {
                u.pin = p;
            }
        }
        if let Some(rm) = field!("running", |v: &Dynamic| v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `running` is a map (show, text)"))) {
            let bad = keys_of(f, "`running` key", &rm, ui::RUNNING_TRAITS);
            let show = rm.get("show").map(|v| one_of(f, "running.show", v, ui::RunShow::parse, ui::RUN_SHOWS)).transpose();
            let words = rm.get("text").map(|v| text(f, "running.text", v)).transpose();
            match (bad.is_empty(), show, words) {
                (true, Ok(s), Ok(t)) => u.running = Running { show: s.unwrap_or(u.running.show), text: t.unwrap_or_default() },
                (_, s, t) => {
                    errors_push(&mut err, bad);
                    for e in [s.err(), t.err()].into_iter().flatten() {
                        err(e);
                    }
                }
            }
        }
        if let Some(x) = field!("refused", |v| one_of(f, "refused", v, ui::Refused::parse, ui::REFUSALS)) {
            u.refused = Some(x);
        }
        if let Some(lm) = field!("look", |v: &Dynamic| v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `look` is a map (icon, clip, effect)"))) {
            match self.look_of(f, name, &lm, &u.look) {
                Ok(l) => u.look = l,
                Err(es) => errors_push(&mut err, es),
            }
        }
        if let Some(x) = field!("marker", |v| one_of(f, "marker", v, ui::Marker::parse, ui::MARKERS)) {
            u.marker = x;
        }
        if let Some(k) = field!("key", |v| text(f, "key", v)) {
            u.key = Some(k);
        }
        if let Some(t) = field!("tip", |v| text(f, "tip", v)) {
            u.tip = Some(t);
        }
        if let Some(i) = input {
            use crate::combat::Aim;
            use ui::Input as I;
            let aim = shape.map(|s| s.aim);
            let why = match i {
                I::AimPoint if !(aim == Some(Aim::Point) || spec.is_some_and(|k| k.needs_target)) => Some("needs a combat aim of `point` or a spec with `target: true`"),
                I::Hold if !shape.is_some_and(|s| s.aim == Aim::Facing || s.hold_ms > 0) => Some("needs a held combat shape (aim `facing`, or `hold_ms`)"),
                I::AimDir if !matches!(aim, Some(Aim::Facing | Aim::Dash)) => Some("needs a combat aim of `facing` or `dash`"),
                I::Toggle if u.toggles.is_none() => Some("needs `toggles`, the body state it switches"),
                I::PickTarget if !u.picks.contains(&Pick::Target) => Some("needs `target` in `picks`"),
                I::PickItem if !u.picks.contains(&Pick::Item) => Some("needs `item` in `picks`"),
                I::PickQty if !u.picks.contains(&Pick::Qty) => Some("needs `qty` in `picks`"),
                I::Words if !u.picks.contains(&Pick::Words) => Some("needs `words` in `picks`"),
                I::DragOnto if u.drag.is_none() => Some("needs `drag`"),
                _ => None,
            };
            match why {
                Some(w) => err(format!("{f}: `input: \"{}\"` {w}", i.as_str())),
                None => u.input = i,
            }
        }
        if u.toggles.is_some() && u.input != ui::Input::Toggle {
            err(format!("{f}: `toggles` is switched by `input: \"toggle\"`"));
            u.toggles = None;
        }
        if way {
            let mut w = u.way.take().unwrap_or_default();
            w.alias = field!("alias", |v| text(f, "alias", v)).or(w.alias);
            w.to_label = field!("to_label", |v| text(f, "to_label", v)).or(w.to_label);
            w.room_label = field!("room_label", |v| text(f, "room_label", v)).or(w.room_label);
            if let Some(b) = field!("bubble", |v| one_of(f, "bubble", v, ui::Bubble::parse, ui::BUBBLES)) {
                w.bubble = Some(b);
            }
            if let Some(rm) = field!("rows", |v: &Dynamic| v.clone().try_cast::<Map>().ok_or_else(|| format!("{f}: `rows` is a map of experience kinds to {}", ui::ROWS.join(", ")))) {
                for (k, v) in rm {
                    match one_of(f, &format!("rows.{k}"), &v, ui::Row::parse, ui::ROWS) {
                        Ok(r) => {
                            w.rows.insert(k.to_string(), r);
                        }
                        Err(e) => err(e),
                    }
                }
            }
            u.way = Some(w);
        }
        u
    }

    /// `look` over the defaults: named icon, clip families and effect, and a clip that does not
    /// contradict how others see the skill (`_shows().look`).
    fn look_of(&self, f: &str, name: &str, m: &Map, base: &Look) -> Result<Look, Vec<String>> {
        let mut errors = keys_of(f, "`look` key", m, ui::LOOK_TRAITS);
        let mut l = base.clone();
        if let Some(v) = m.get("icon") {
            match text(f, "look.icon", v).and_then(|s| named(f, "look.icon", &s, ui::ICONS)) {
                Ok(i) => l.icon = Some(i),
                Err(e) => errors.push(e),
            }
        }
        if let Some(v) = m.get("clip") {
            match texts(f, "look.clip", v).and_then(|cs| cs.iter().map(|c| named(f, "look.clip", c, ui::CLIPS)).collect::<Result<Vec<_>, _>>()) {
                Ok(cs) if cs.is_empty() => errors.push(format!("{f}: `look.clip` names at least one clip family")),
                Ok(cs) => {
                    let shown = self.shows.get(name).and_then(|s| ui::name_in(ui::CLIPS, &s.look));
                    match shown {
                        Some(s) if !cs.contains(&s) => errors.push(format!("{f}: `look.clip` contradicts `{name}_shows()`, whose look is `{s}`: others see it as that")),
                        _ => l.clips = cs,
                    }
                }
                Err(e) => errors.push(e),
            }
        }
        if let Some(v) = m.get("effect") {
            match text(f, "look.effect", v).and_then(|s| if s == "none" { Ok(None) } else { named(f, "look.effect", &s, ui::EFFECTS).map(Some) }) {
                Ok(e) => l.effect = e,
                Err(e) => errors.push(e),
            }
        }
        if errors.is_empty() {
            Ok(l)
        } else {
            Err(errors)
        }
    }

    /// `detail` is a function of one name, called on each of the spec's items, that returns words.
    /// For a recipe grid (`source: "products"`), it is called on each product.
    fn detail_errors(&self, f: &str, d: &str, name: &str, source: Option<ui::ItemSource>, spec: Option<&crate::catalog::SkillSpec>) -> Option<String> {
        if !self.unary.contains(d) {
            return Some(format!("{f}: `detail` names a function of one name in the script (`fn {d}(name)`), and there is none"));
        }
        let choices: Vec<String> = if source == Some(ui::ItemSource::Products) { self.products_of(name).into_iter().map(String::from).collect() } else { spec.map(|k| k.items.clone()).unwrap_or_default() };
        for item in &choices {
            match self.engine.call_fn::<Dynamic>(&mut Scope::new(), &self.ast, d, (item.clone(),)) {
                Ok(v) if v.is_string() => {}
                Ok(v) => return Some(format!("{f}: `detail`: `{d}(\"{item}\")` must return words, got {}", v.type_name())),
                Err(e) => return Some(format!("{f}: `detail`: `{d}(\"{item}\")` failed: {e}")),
            }
        }
        None
    }

    /// How a skill (or way of speaking) is presented: its `<name>_ui()` over its defaults. None
    /// for a name that is neither.
    pub fn ui(&self, name: &str) -> Option<&UiSpec> {
        self.ui.specs.get(name)
    }

    /// Every skill's (and declared way's) presentation, in the script's order.
    pub fn ui_specs(&self) -> impl Iterator<Item = &UiSpec> {
        self.ui.order.iter().filter_map(|n| self.ui.specs.get(n))
    }

    /// A skill's presentation had it declared nothing.
    pub fn ui_default(&self, name: &str) -> Option<UiSpec> {
        (self.skills.get(name).is_some() || self.shapes.get(name).is_some()).then(|| ui::defaults(&self.ui_source(name, &self.ui.missiles)))
    }

    /// What was wrong with the script's interface declarations, each naming its function; each
    /// such field plays with its default. An install refuses any (`validate`); a client logs
    /// them once and plays on.
    pub fn ui_errors(&self) -> &[String] {
        &self.ui.errors
    }

    /// The skills that may go on the bar, for `ui::bar_places`: `skill_bar()` in its order, then
    /// any other skill declared on the bar, in the script's order.
    pub(crate) fn bar_entries(&self) -> Vec<ui::BarEntry> {
        let entry = |n: &str| {
            let shape = self.shapes.get(n);
            let u = self.ui.specs.get(n);
            ui::BarEntry {
                name: n.to_string(),
                aim: shape.map_or(crate::combat::Aim::None, |s| s.aim),
                evades: shape.is_some_and(|s| s.evades),
                radius: self.ui.missiles.get(n).map_or(0.0, |m| m.radius),
                place: u.and_then(|u| u.place),
                order: u.and_then(|u| u.order),
            }
        };
        let bar = self.shapes.bar();
        let mut out: Vec<ui::BarEntry> = bar.iter().map(|n| entry(n)).collect();
        out.extend(self.ui_specs().filter(|u| u.is_on(On::Bar) && u.way.is_none() && !bar.contains(&u.name)).map(|u| entry(&u.name)));
        out
    }
}

fn errors_push(err: &mut impl FnMut(String), es: Vec<String>) {
    for e in es {
        err(e);
    }
}
