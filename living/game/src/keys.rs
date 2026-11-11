//! Key bindings: every key the game reads for play goes through [`Binds`], so all of them can be
//! changed in Settings › Controls (interface D, 2026-11-11).
//!
//! - **Defaults** (`Preset::Letters`): WASD moves, Shift held runs, Space jumps (the owner's
//!   wish), a double tap of a direction key dodges that way, X sheathes or draws; LMB strikes and
//!   RMB shoots the bow; Q blocks, E heals, R casts the fire bolt, and 1–3 are their twins;
//!   skills the rules add take 4–9; F acts on what you point at (held: more acts), Enter talks,
//!   Tab changes whom you speak to; G waves, B nods, V looks someone over; I the pack, C the
//!   character, K skills and know-how, L the log and people; ⌥ held glances with the camera.
//! - **Presets:** "Q E R, plus 1–9" (the default), "1–9 only" (the skills on the number row,
//!   Q E R freed), and "My own" (any change).
//! - **Stored** in a small local file, a per-viewer convenience like a window position:
//!   `LIVING_GAME_SETTINGS`, else `~/.config/slop-art-online/game.json`, with the other settings
//!   (control scheme, edge of sight, tips, the weapon drawing itself). A missing or unreadable
//!   file means the defaults.
//!
//! Which skill a skill key uses comes from the rules' bar, by how each skill is aimed
//! (`combat::Roles`): the keys name places on the bar, not skills.

use bevy::prelude::*;
use std::collections::HashMap;

/// A second press of a direction key within this long dodges (s).
pub const DOUBLE_TAP_S: f64 = 0.28;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Bind {
    Key(KeyCode),
    Mouse(MouseButton),
    /// A double tap of a direction key (the dodge's default).
    DoubleTap,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub enum Act {
    Forward,
    Back,
    Left,
    Right,
    Run,
    Jump,
    Dodge,
    Weapon,
    /// The bar's mouse slots and its three skill keys.
    Primary,
    Secondary,
    Skill1,
    Skill2,
    Skill3,
    /// Skills the rules add beyond the main row: 4–9.
    Extra(u8),
    Interact,
    Talk,
    Address,
    Wave,
    Nod,
    LookOver,
    Pack,
    Character,
    Skills,
    Log,
    Glance,
}

pub const EXTRA: u8 = 6;

impl Act {
    pub fn all() -> Vec<Act> {
        let mut v = vec![Act::Forward, Act::Back, Act::Left, Act::Right, Act::Run, Act::Jump, Act::Dodge, Act::Weapon, Act::Primary, Act::Secondary, Act::Skill1, Act::Skill2, Act::Skill3];
        v.extend((0..EXTRA).map(Act::Extra));
        v.extend([Act::Interact, Act::Talk, Act::Address, Act::Wave, Act::Nod, Act::LookOver, Act::Pack, Act::Character, Act::Skills, Act::Log, Act::Glance]);
        v
    }

    pub fn name(self) -> String {
        match self {
            Act::Extra(i) => format!("Extra{}", i + 4),
            a => format!("{a:?}"),
        }
    }

    fn parse(s: &str) -> Option<Act> {
        if let Some(n) = s.strip_prefix("Extra") {
            let n: u8 = n.parse().ok()?;
            return (4..4 + EXTRA).contains(&n).then(|| Act::Extra(n - 4));
        }
        Act::all().into_iter().find(|a| a.name() == s)
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Preset {
    /// Q E R for the three skills, with 1–3 as their twins, 4–9 for more.
    #[default]
    Letters,
    /// The skills on 1–9 only.
    Numbers,
    /// Anything else.
    Own,
}

impl Preset {
    pub fn name(self) -> &'static str {
        match self {
            Preset::Letters => "letters",
            Preset::Numbers => "numbers",
            Preset::Own => "own",
        }
    }
}

#[derive(Resource, Clone, Debug, PartialEq)]
pub struct Binds {
    pub map: HashMap<Act, Vec<Bind>>,
    pub preset: Preset,
}

impl Default for Binds {
    fn default() -> Self {
        Self::preset(Preset::Letters)
    }
}

const DIGITS: [KeyCode; 10] = [KeyCode::Digit0, KeyCode::Digit1, KeyCode::Digit2, KeyCode::Digit3, KeyCode::Digit4, KeyCode::Digit5, KeyCode::Digit6, KeyCode::Digit7, KeyCode::Digit8, KeyCode::Digit9];

impl Binds {
    pub fn preset(p: Preset) -> Self {
        use Bind::{Key as K, Mouse as M};
        use KeyCode::*;
        let mut map: HashMap<Act, Vec<Bind>> = HashMap::new();
        let mut set = |a: Act, b: Vec<Bind>| {
            map.insert(a, b);
        };
        set(Act::Forward, vec![K(KeyW)]);
        set(Act::Back, vec![K(KeyS)]);
        set(Act::Left, vec![K(KeyA)]);
        set(Act::Right, vec![K(KeyD)]);
        set(Act::Run, vec![K(ShiftLeft), K(ShiftRight)]);
        set(Act::Jump, vec![K(Space)]);
        set(Act::Dodge, vec![Bind::DoubleTap]);
        set(Act::Weapon, vec![K(KeyX)]);
        set(Act::Primary, vec![M(MouseButton::Left)]);
        set(Act::Secondary, vec![M(MouseButton::Right)]);
        match p {
            Preset::Numbers => {
                set(Act::Skill1, vec![K(Digit1)]);
                set(Act::Skill2, vec![K(Digit2)]);
                set(Act::Skill3, vec![K(Digit3)]);
            }
            _ => {
                set(Act::Skill1, vec![K(KeyQ), K(Digit1)]);
                set(Act::Skill2, vec![K(KeyE), K(Digit2)]);
                set(Act::Skill3, vec![K(KeyR), K(Digit3)]);
            }
        }
        for i in 0..EXTRA {
            set(Act::Extra(i), vec![K(DIGITS[(4 + i as usize) % 10])]);
        }
        set(Act::Interact, vec![K(KeyF)]);
        set(Act::Talk, vec![K(Enter)]);
        set(Act::Address, vec![K(Tab)]);
        set(Act::Wave, vec![K(KeyG)]);
        set(Act::Nod, vec![K(KeyB)]);
        set(Act::LookOver, vec![K(KeyV)]);
        set(Act::Pack, vec![K(KeyI)]);
        set(Act::Character, vec![K(KeyC)]);
        set(Act::Skills, vec![K(KeyK)]);
        set(Act::Log, vec![K(KeyL)]);
        set(Act::Glance, vec![K(AltLeft), K(AltRight)]);
        Binds { map, preset: p }
    }

    pub fn get(&self, a: Act) -> &[Bind] {
        self.map.get(&a).map_or(&[], |v| v.as_slice())
    }

    pub fn keys(&self, a: Act) -> impl Iterator<Item = KeyCode> + '_ {
        self.get(a).iter().filter_map(|b| match b {
            Bind::Key(k) => Some(*k),
            _ => None,
        })
    }

    pub fn just_pressed(&self, a: Act, keys: &ButtonInput<KeyCode>) -> bool {
        self.keys(a).any(|k| keys.just_pressed(k))
    }

    pub fn pressed(&self, a: Act, keys: &ButtonInput<KeyCode>) -> bool {
        self.keys(a).any(|k| keys.pressed(k))
    }

    pub fn just_released(&self, a: Act, keys: &ButtonInput<KeyCode>) -> bool {
        self.keys(a).any(|k| keys.just_released(k))
    }

    /// Mouse bindings too.
    pub fn down(&self, a: Act, keys: &ButtonInput<KeyCode>, mouse: &ButtonInput<MouseButton>) -> bool {
        self.get(a).iter().any(|b| match b {
            Bind::Key(k) => keys.pressed(*k),
            Bind::Mouse(m) => mouse.pressed(*m),
            Bind::DoubleTap => false,
        })
    }

    pub fn went_down(&self, a: Act, keys: &ButtonInput<KeyCode>, mouse: &ButtonInput<MouseButton>) -> bool {
        self.get(a).iter().any(|b| match b {
            Bind::Key(k) => keys.just_pressed(*k),
            Bind::Mouse(m) => mouse.just_pressed(*m),
            Bind::DoubleTap => false,
        })
    }

    pub fn went_up(&self, a: Act, keys: &ButtonInput<KeyCode>, mouse: &ButtonInput<MouseButton>) -> bool {
        self.get(a).iter().any(|b| match b {
            Bind::Key(k) => keys.just_released(*k),
            Bind::Mouse(m) => mouse.just_released(*m),
            Bind::DoubleTap => false,
        })
    }

    /// The act a key or button is bound to, if any (a swap offers it back).
    pub fn holder(&self, b: Bind) -> Option<(Act, usize)> {
        Act::all().into_iter().find_map(|a| self.get(a).iter().position(|x| *x == b).map(|i| (a, i)))
    }

    /// Bind `b` as `a`'s `slot`th key. A key already in use is swapped: its old act takes what
    /// `a` had there (or loses it, if `a` had nothing). The preset becomes "My own" unless the
    /// result is one of the presets.
    pub fn rebind(&mut self, a: Act, slot: usize, b: Bind) {
        let old = self.get(a).get(slot).copied();
        if let Some((other, i)) = self.holder(b).filter(|(o, i)| (*o, *i) != (a, slot)) {
            let list = self.map.entry(other).or_default();
            match old {
                Some(o) => list[i] = o,
                None => {
                    list.remove(i);
                }
            }
        }
        let list = self.map.entry(a).or_default();
        if slot < list.len() {
            list[slot] = b;
        } else {
            list.push(b);
        }
        self.preset = [Preset::Letters, Preset::Numbers].into_iter().find(|p| Binds::preset(*p).map == self.map).unwrap_or(Preset::Own);
    }

    /// A short label for a binding, as the chips show it.
    pub fn label(b: Bind) -> String {
        match b {
            Bind::Mouse(MouseButton::Left) => "LMB".into(),
            Bind::Mouse(MouseButton::Right) => "RMB".into(),
            Bind::Mouse(MouseButton::Middle) => "MMB".into(),
            Bind::Mouse(_) => "Mouse".into(),
            Bind::DoubleTap => "2× dir".into(),
            Bind::Key(k) => key_label(k),
        }
    }

    /// The label of an act's first binding ("" if none).
    pub fn first(&self, a: Act) -> String {
        self.get(a).first().map(|b| Binds::label(*b)).unwrap_or_default()
    }
}

/// Keys by name, for the settings file and the live script (`key:NAME`).
const KEYS: &[(&str, KeyCode)] = &[
    ("KeyA", KeyCode::KeyA), ("KeyB", KeyCode::KeyB), ("KeyC", KeyCode::KeyC), ("KeyD", KeyCode::KeyD), ("KeyE", KeyCode::KeyE), ("KeyF", KeyCode::KeyF), ("KeyG", KeyCode::KeyG),
    ("KeyH", KeyCode::KeyH), ("KeyI", KeyCode::KeyI), ("KeyJ", KeyCode::KeyJ), ("KeyK", KeyCode::KeyK), ("KeyL", KeyCode::KeyL), ("KeyM", KeyCode::KeyM), ("KeyN", KeyCode::KeyN),
    ("KeyO", KeyCode::KeyO), ("KeyP", KeyCode::KeyP), ("KeyQ", KeyCode::KeyQ), ("KeyR", KeyCode::KeyR), ("KeyS", KeyCode::KeyS), ("KeyT", KeyCode::KeyT), ("KeyU", KeyCode::KeyU),
    ("KeyV", KeyCode::KeyV), ("KeyW", KeyCode::KeyW), ("KeyX", KeyCode::KeyX), ("KeyY", KeyCode::KeyY), ("KeyZ", KeyCode::KeyZ),
    ("Digit0", KeyCode::Digit0), ("Digit1", KeyCode::Digit1), ("Digit2", KeyCode::Digit2), ("Digit3", KeyCode::Digit3), ("Digit4", KeyCode::Digit4), ("Digit5", KeyCode::Digit5),
    ("Digit6", KeyCode::Digit6), ("Digit7", KeyCode::Digit7), ("Digit8", KeyCode::Digit8), ("Digit9", KeyCode::Digit9),
    ("Space", KeyCode::Space), ("Enter", KeyCode::Enter), ("Tab", KeyCode::Tab), ("Escape", KeyCode::Escape), ("Backspace", KeyCode::Backspace),
    ("ShiftLeft", KeyCode::ShiftLeft), ("ShiftRight", KeyCode::ShiftRight), ("ControlLeft", KeyCode::ControlLeft), ("ControlRight", KeyCode::ControlRight),
    ("AltLeft", KeyCode::AltLeft), ("AltRight", KeyCode::AltRight), ("SuperLeft", KeyCode::SuperLeft), ("CapsLock", KeyCode::CapsLock),
    ("ArrowUp", KeyCode::ArrowUp), ("ArrowDown", KeyCode::ArrowDown), ("ArrowLeft", KeyCode::ArrowLeft), ("ArrowRight", KeyCode::ArrowRight),
    ("Backquote", KeyCode::Backquote), ("Minus", KeyCode::Minus), ("Equal", KeyCode::Equal), ("BracketLeft", KeyCode::BracketLeft), ("BracketRight", KeyCode::BracketRight),
    ("Semicolon", KeyCode::Semicolon), ("Quote", KeyCode::Quote), ("Comma", KeyCode::Comma), ("Period", KeyCode::Period), ("Slash", KeyCode::Slash), ("Backslash", KeyCode::Backslash),
    ("F1", KeyCode::F1), ("F2", KeyCode::F2), ("F3", KeyCode::F3), ("F4", KeyCode::F4), ("F5", KeyCode::F5), ("F6", KeyCode::F6), ("F7", KeyCode::F7), ("F8", KeyCode::F8),
];

pub fn key_named(name: &str) -> Option<KeyCode> {
    KEYS.iter().find(|(n, _)| *n == name).map(|(_, k)| *k)
}

pub fn key_name(k: KeyCode) -> Option<&'static str> {
    KEYS.iter().find(|(_, c)| *c == k).map(|(n, _)| *n)
}

/// Every key the bindings know, for listening to a new one.
pub fn all_keys() -> impl Iterator<Item = KeyCode> {
    KEYS.iter().map(|(_, k)| *k)
}

pub fn key_label(k: KeyCode) -> String {
    let n = key_name(k).unwrap_or("?");
    if let Some(l) = n.strip_prefix("Key").or_else(|| n.strip_prefix("Digit")) {
        return l.to_string();
    }
    match n {
        "ShiftLeft" | "ShiftRight" => "Shift".into(),
        "ControlLeft" | "ControlRight" => "Ctrl".into(),
        "AltLeft" | "AltRight" => "⌥".into(),
        "SuperLeft" => "Cmd".into(),
        "Escape" => "Esc".into(),
        "Backspace" => "Bksp".into(),
        "ArrowUp" => "Up".into(),
        "ArrowDown" => "Down".into(),
        "ArrowLeft" => "Left".into(),
        "ArrowRight" => "Right".into(),
        "Backquote" => "`".into(),
        "Minus" => "-".into(),
        "Equal" => "=".into(),
        "BracketLeft" => "[".into(),
        "BracketRight" => "]".into(),
        "Semicolon" => ";".into(),
        "Quote" => "'".into(),
        "Comma" => ",".into(),
        "Period" => ".".into(),
        "Slash" => "/".into(),
        "Backslash" => "\\".into(),
        "CapsLock" => "Caps".into(),
        other => other.into(),
    }
}

fn bind_name(b: Bind) -> String {
    match b {
        Bind::Key(k) => key_name(k).unwrap_or("?").to_string(),
        Bind::Mouse(MouseButton::Left) => "MouseLeft".into(),
        Bind::Mouse(MouseButton::Right) => "MouseRight".into(),
        Bind::Mouse(_) => "MouseMiddle".into(),
        Bind::DoubleTap => "DoubleTap".into(),
    }
}

fn bind_parse(s: &str) -> Option<Bind> {
    match s {
        "MouseLeft" => Some(Bind::Mouse(MouseButton::Left)),
        "MouseRight" => Some(Bind::Mouse(MouseButton::Right)),
        "MouseMiddle" => Some(Bind::Mouse(MouseButton::Middle)),
        "DoubleTap" => Some(Bind::DoubleTap),
        k => key_named(k).map(Bind::Key),
    }
}

// ---- the settings file ----------------------------------------------------------------------

/// What a viewer keeps between sessions: the bindings and the Play settings.
#[derive(Resource, Clone, Debug, PartialEq)]
pub struct Prefs {
    pub control: crate::controls::Control,
    /// `unseen`, `limited` or `fade` (`sightedge::Mode`).
    pub sight_edge: Option<String>,
    pub tips: bool,
    /// The weapon draws itself when something attacks you.
    pub auto_draw: bool,
    /// Changed by a shortcut (F2, F3): saved by Settings' update.
    pub dirty: bool,
}

impl Default for Prefs {
    fn default() -> Self {
        Self { control: crate::controls::Control::default(), sight_edge: None, tips: true, auto_draw: true, dirty: false }
    }
}

pub fn path() -> std::path::PathBuf {
    if let Some(p) = std::env::var("LIVING_GAME_SETTINGS").ok().filter(|p| !p.is_empty()) {
        return p.into();
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    std::path::Path::new(&home).join(".config/slop-art-online/game.json")
}

pub fn load() -> (Binds, Prefs) {
    let p = path();
    let Ok(text) = std::fs::read_to_string(&p) else { return (Binds::default(), Prefs::default()) };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) else {
        warn!("settings: {} is not JSON; using the defaults", p.display());
        return (Binds::default(), Prefs::default());
    };
    let preset = match v["preset"].as_str() {
        Some("numbers") => Preset::Numbers,
        Some("own") => Preset::Own,
        _ => Preset::Letters,
    };
    let mut binds = Binds::preset(if preset == Preset::Own { Preset::Letters } else { preset });
    if let Some(m) = v["binds"].as_object() {
        for (k, list) in m {
            let (Some(a), Some(list)) = (Act::parse(k), list.as_array()) else { continue };
            binds.map.insert(a, list.iter().filter_map(|b| b.as_str().and_then(bind_parse)).collect());
        }
    }
    binds.preset = [Preset::Letters, Preset::Numbers].into_iter().find(|p| Binds::preset(*p).map == binds.map).unwrap_or(Preset::Own);
    let d = Prefs::default();
    let prefs = Prefs {
        control: match v["control"].as_str() {
            Some("cursor") => crate::controls::Control::Cursor,
            Some("travel") => crate::controls::Control::Travel,
            _ => d.control,
        },
        sight_edge: v["sight_edge"].as_str().map(String::from),
        tips: v["tips"].as_bool().unwrap_or(d.tips),
        auto_draw: v["auto_draw"].as_bool().unwrap_or(d.auto_draw),
        dirty: false,
    };
    info!("settings: read {} ({} preset)", p.display(), binds.preset.name());
    (binds, prefs)
}

pub fn save(binds: &Binds, prefs: &Prefs) {
    let p = path();
    let map: serde_json::Map<String, serde_json::Value> = Act::all().into_iter().map(|a| (a.name(), serde_json::Value::from(binds.get(a).iter().map(|b| bind_name(*b)).collect::<Vec<_>>()))).collect();
    let v = serde_json::json!({
        "preset": binds.preset.name(),
        "binds": map,
        "control": match prefs.control { crate::controls::Control::Cursor => "cursor", crate::controls::Control::Travel => "travel" },
        "sight_edge": prefs.sight_edge,
        "tips": prefs.tips,
        "auto_draw": prefs.auto_draw,
    });
    if let Some(dir) = p.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    match std::fs::write(&p, serde_json::to_string_pretty(&v).unwrap_or_default()) {
        Ok(()) => info!("settings: saved {}", p.display()),
        Err(e) => warn!("settings: could not save {}: {e}", p.display()),
    }
}

// ---- double taps ------------------------------------------------------------------------------

/// A double tap of a direction key this frame (the dodge's default), as a direction in the
/// keys' frame: forward +y, right +x.
#[derive(Resource, Default)]
pub struct DoubleTap {
    last: HashMap<Act, f64>,
    pub fired: Option<Vec2>,
    /// A script's double tap (`dodge:DIR`), through the same path.
    pub scripted: Option<Act>,
}

pub fn double_tap(keys: Res<ButtonInput<KeyCode>>, binds: Res<Binds>, input: Res<crate::controls::Input>, wants: Res<crate::hud::UiWants>, time: Res<Time>, mut d: ResMut<DoubleTap>) {
    d.fired = None;
    let now = time.elapsed_secs_f64();
    let typing = input.chat_open || wants.keyboard;
    let dirs = [(Act::Forward, Vec2::Y), (Act::Back, Vec2::NEG_Y), (Act::Left, Vec2::NEG_X), (Act::Right, Vec2::X)];
    let scripted = d.scripted.take();
    for (a, v) in dirs {
        let pressed = (!typing && binds.just_pressed(a, &keys)) || scripted == Some(a);
        if !pressed {
            continue;
        }
        let again = scripted == Some(a) || d.last.get(&a).is_some_and(|t| now - t <= DOUBLE_TAP_S);
        if again {
            d.fired = Some(v);
            d.last.remove(&a);
        } else {
            d.last.insert(a, now);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_taken_key_is_swapped_and_the_preset_follows() {
        let mut b = Binds::default();
        assert_eq!(b.preset, Preset::Letters);
        b.rebind(Act::Dodge, 0, Bind::Key(KeyCode::Space));
        // Space was the jump's: the jump gets the dodge's old binding.
        assert_eq!(b.get(Act::Dodge), &[Bind::Key(KeyCode::Space)]);
        assert_eq!(b.get(Act::Jump), &[Bind::DoubleTap]);
        assert_eq!(b.preset, Preset::Own);
        b.rebind(Act::Dodge, 0, Bind::DoubleTap);
        assert_eq!(b.get(Act::Jump), &[Bind::Key(KeyCode::Space)]);
        assert_eq!(b.preset, Preset::Letters);
    }

    #[test]
    fn the_number_preset_frees_q_e_r() {
        let b = Binds::preset(Preset::Numbers);
        assert_eq!(b.holder(Bind::Key(KeyCode::KeyQ)), None);
        assert_eq!(b.holder(Bind::Key(KeyCode::Digit1)), Some((Act::Skill1, 0)));
        assert_eq!(b.holder(Bind::Key(KeyCode::Digit9)), Some((Act::Extra(5), 0)));
        assert_eq!(key_label(KeyCode::AltLeft), "⌥");
    }
}
