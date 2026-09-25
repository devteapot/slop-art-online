//! Per-frame snapshot of the hot tables and the viewer's persistent state and caches.

use crate::net::Net;
use bevy_egui::egui;
use living_bindings::*;
use living_rules::map::{Map, Terrain, MAP_H, MAP_W};
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// Rows cloned from the client cache once per frame (tens of creatures).
#[derive(Default)]
pub struct Snap {
    pub now: u64,
    pub world: Option<World>,
    pub stats: Option<Stats>,
    pub chars: HashMap<u32, Character>,
    pub bodies: HashMap<u32, Body>,
    pub vitals: HashMap<u32, Vitals>,
    pub activity: HashMap<u32, Activity>,
    pub personas: HashMap<u32, Persona>,
    pub resources: Vec<ResourceNode>,
    pub structures: Vec<Structure>,
    pub expecting: Vec<Expecting>,
    pub bond_offers: Vec<BondOffer>,
}

impl Snap {
    pub fn take(net: &Net) -> Self {
        let now = crate::clock::now_ms();
        let Some(c) = &net.conn else {
            return Self { now, ..Default::default() };
        };
        Self {
            now,
            world: c.db.world().iter().next(),
            stats: c.db.stats().iter().next(),
            chars: c.db.character().iter().map(|r| (r.id, r)).collect(),
            bodies: c.db.body().iter().map(|r| (r.id, r)).collect(),
            vitals: c.db.vitals().iter().map(|r| (r.id, r)).collect(),
            activity: c.db.activity().iter().map(|r| (r.id, r)).collect(),
            personas: c.db.persona().iter().map(|r| (r.id, r)).collect(),
            resources: c.db.resource_node().iter().collect(),
            structures: c.db.structure().iter().collect(),
            expecting: c.db.expecting().iter().collect(),
            bond_offers: c.db.bond_offer().iter().collect(),
        }
    }

    pub fn day_ms(&self) -> u64 {
        self.world.as_ref().map(|w| w.day_ms.max(1)).unwrap_or(living_rules::DEFAULT_DAY_MS)
    }
    pub fn epoch_ms(&self) -> u64 {
        self.world.as_ref().map(|w| w.epoch_ms).unwrap_or(self.now)
    }
    pub fn hour_at(&self, t: u64) -> f32 {
        living_rules::hour_of(t, self.epoch_ms(), self.day_ms())
    }
    pub fn hour(&self) -> f32 {
        self.hour_at(self.now)
    }
    /// "day 2 14:05"
    pub fn stamp(&self, t: u64) -> String {
        let d = living_rules::day_of(t, self.epoch_ms(), self.day_ms());
        format!("day {d} {}", hhmm(self.hour_at(t)))
    }

    /// Kinematic position at `now` (tile coordinates).
    pub fn body_pos(&self, id: u32) -> Option<egui::Pos2> {
        self.bodies.get(&id).map(|b| body_pos(b, self.now))
    }

    /// Age in world days.
    pub fn age_days(&self, c: &Character) -> f32 {
        let end = if c.alive { self.now } else { c.died_ms.max(c.born_ms) };
        c.birth_age_days + end.saturating_sub(c.born_ms) as f32 / self.day_ms() as f32
    }
    pub fn is_child(&self, c: &Character) -> bool {
        c.kind == "person" && self.age_days(c) < 3.0
    }

    pub fn name(&self, id: u32) -> String {
        match self.chars.get(&id) {
            Some(c) if c.kind == "person" => c.name.clone(),
            Some(c) => format!("{} #{}", c.name, c.id),
            None if id == 0 => "—".into(),
            None => format!("#{id}"),
        }
    }
}

pub fn hhmm(h: f32) -> String {
    let m = (h * 60.0) as u32;
    format!("{:02}:{:02}", (m / 60) % 24, m % 60)
}

pub fn body_pos(b: &Body, now: u64) -> egui::Pos2 {
    let t = now.min(b.next_ms);
    let dt = t.saturating_sub(b.t_ms) as f32 / 1000.0;
    egui::pos2(b.x + b.vx * dt, b.y + b.vy * dt)
}

/// A need anchored at `at_ms` changing at `rate` per minute.
pub fn need(value: f32, rate: f32, at_ms: u64, now: u64, max: f32) -> f32 {
    let mins = now.saturating_sub(at_ms) as f32 / 60000.0;
    (value + rate * mins).clamp(0.0, max)
}

pub fn person_color(id: u32) -> egui::Color32 {
    let h = (id as f32 * 0.618_034).fract();
    egui::ecolor::Hsva::new(h, 0.62, 0.95, 1.0).into()
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Identity,
    Behavior,
    Mind,
    Experiences,
    Thoughts,
}

pub struct View {
    pub center: egui::Pos2,
    /// Screen points per tile.
    pub zoom: f32,
    pub fitted: bool,
    pub selected: Option<u32>,
    pub follow: bool,
    pub tab: Tab,
    pub story_only_selected: bool,
    /// Experience to highlight (and scroll to once) after following a thought's evidence.
    pub exp_highlight: Option<u64>,
    pub exp_scroll: bool,
    last_selected: Option<u32>,
    pub terrain: Option<egui::TextureHandle>,
    pub map: Option<Map>,
    pub chronicle: Vec<Chronicle>,
    pub thoughts: HashMap<u32, Vec<Thought>>,
    /// Experience ids a consolidate thought integrated (from its detail JSON).
    pub thought_exps: HashMap<u64, Vec<u64>>,
    /// Smoothed display positions (tile coordinates).
    pub shown: HashMap<u32, egui::Pos2>,
    /// Smoothed frame rate and UI build time (diagnostics in the top bar).
    pub fps: f32,
    pub frame_ms: f32,
    gens: (u32, u32, u32),
    styled: bool,
}

impl Default for View {
    fn default() -> Self {
        Self {
            center: egui::pos2(MAP_W as f32 / 2.0, MAP_H as f32 / 2.0),
            zoom: 8.0,
            fitted: false,
            selected: None,
            follow: false,
            tab: Tab::Identity,
            story_only_selected: false,
            exp_highlight: None,
            exp_scroll: false,
            last_selected: None,
            terrain: None,
            map: None,
            chronicle: Vec::new(),
            thoughts: HashMap::new(),
            thought_exps: HashMap::new(),
            shown: HashMap::new(),
            fps: 60.0,
            frame_ms: 0.0,
            gens: (u32::MAX, u32::MAX, u32::MAX),
            styled: false,
        }
    }
}

impl View {
    pub fn style(&mut self, ctx: &egui::Context) {
        if self.styled {
            return;
        }
        self.styled = true;
        let mut v = egui::Visuals::dark();
        v.panel_fill = egui::Color32::from_rgb(22, 26, 31);
        v.window_fill = egui::Color32::from_rgb(26, 30, 36);
        v.extreme_bg_color = egui::Color32::from_rgb(14, 17, 21);
        v.faint_bg_color = egui::Color32::from_rgb(30, 35, 42);
        v.selection.bg_fill = egui::Color32::from_rgb(58, 92, 128);
        v.hyperlink_color = egui::Color32::from_rgb(140, 190, 255);
        ctx.set_visuals(v);
        // Hack covers arrows and geometric shapes (→, ●, ⌂) missing from the default UI font.
        let mut fonts = egui::FontDefinitions::default();
        if let Some(f) = fonts.families.get_mut(&egui::FontFamily::Proportional) {
            f.push("Hack".into());
        }
        ctx.set_fonts(fonts);
        ctx.style_mut(|s| {
            s.spacing.item_spacing = egui::vec2(6.0, 5.0);
            s.spacing.button_padding = egui::vec2(8.0, 3.0);
        });
    }

    pub fn select(&mut self, id: u32, snap: &Snap, center: bool) {
        self.selected = Some(id);
        if center {
            if let Some(p) = snap.body_pos(id) {
                self.center = p;
            }
        }
    }

    pub fn refresh(&mut self, ctx: &egui::Context, net: &Net, snap: &Snap, dt: f32) {
        let gens = net.gens.get();
        if let Some(c) = &net.conn {
            if gens.0 != self.gens.0 {
                let chunks: Vec<(u32, Vec<u8>)> = c.db.terrain_chunk().iter().map(|r| (r.id, r.tiles)).collect();
                if chunks.is_empty() {
                    self.map = None;
                    self.terrain = None;
                } else {
                    let map = Map::from_chunks(chunks);
                    self.terrain = Some(ctx.load_texture("terrain", terrain_image(&map), egui::TextureOptions::NEAREST));
                    self.map = Some(map);
                }
            }
            if gens.1 != self.gens.1 {
                let mut rows: Vec<Chronicle> = c.db.chronicle().iter().collect();
                rows.sort_by(|a, b| b.at_ms.cmp(&a.at_ms).then(b.id.cmp(&a.id)));
                self.chronicle = rows;
            }
            if gens.2 != self.gens.2 {
                let mut by: HashMap<u32, Vec<Thought>> = HashMap::new();
                for t in c.db.thought().iter() {
                    by.entry(t.actor).or_default().push(t);
                }
                for v in by.values_mut() {
                    v.sort_by(|a, b| b.at_ms.cmp(&a.at_ms).then(b.id.cmp(&a.id)));
                }
                for t in by.values().flatten() {
                    if self.thought_exps.contains_key(&t.id) || t.kind != "consolidate" {
                        continue;
                    }
                    let ids = serde_json::from_str::<serde_json::Value>(&t.detail)
                        .ok()
                        .and_then(|v| v.get("experiences").and_then(|e| e.as_array()).map(|a| a.iter().filter_map(|x| x.as_u64()).collect()))
                        .unwrap_or_default();
                    self.thought_exps.insert(t.id, ids);
                }
                self.thoughts = by;
            }
            self.gens = gens;
        }
        if self.selected != self.last_selected {
            self.last_selected = self.selected;
            self.exp_highlight = None;
        }
        // Ease displayed positions towards the kinematic ones; snap on large corrections.
        let k = 1.0 - (-dt * 14.0).exp();
        self.shown.retain(|id, _| snap.bodies.contains_key(id));
        for (id, b) in &snap.bodies {
            let target = body_pos(b, snap.now);
            let p = self.shown.entry(*id).or_insert(target);
            if (target - *p).length() > 4.0 {
                *p = target;
            } else {
                *p += (target - *p) * k;
            }
        }
        if self.follow {
            if let Some(p) = self.selected.and_then(|id| self.shown.get(&id)) {
                self.center = *p;
            }
        }
    }

    pub fn model_of(&self, id: u32) -> Option<&str> {
        self.thoughts.get(&id)?.iter().find(|t| !t.model.is_empty()).map(|t| t.model.as_str())
    }
}

fn terrain_rgb(t: Terrain) -> [u8; 3] {
    match t {
        Terrain::Grass => [106, 150, 74],
        Terrain::Forest => [52, 98, 56],
        Terrain::Water => [58, 112, 168],
        Terrain::Sand => [214, 196, 140],
        Terrain::Rock => [128, 128, 132],
        Terrain::Dirt => [140, 108, 72],
    }
}

fn hash(x: u32, y: u32) -> f32 {
    let mut h = x.wrapping_mul(374_761_393) ^ y.wrapping_mul(668_265_263);
    h = (h ^ (h >> 13)).wrapping_mul(1_274_126_177);
    ((h ^ (h >> 16)) & 0xffff) as f32 / 65535.0
}

/// One pixel per tile with slight per-tile variation and shoreline shading.
fn terrain_image(map: &Map) -> egui::ColorImage {
    let (w, h) = (MAP_W as usize, MAP_H as usize);
    let mut px = Vec::with_capacity(w * h);
    for y in 0..h as i32 {
        for x in 0..w as i32 {
            let t = map.get(x, y);
            let [r, g, b] = terrain_rgb(t);
            let mut f = 0.94 + 0.10 * hash(x as u32, y as u32);
            if t == Terrain::Water {
                let shore = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                    .iter()
                    .any(|(dx, dy)| x + dx >= 0 && y + dy >= 0 && x + dx < w as i32 && y + dy < h as i32 && map.get(x + dx, y + dy) != Terrain::Water);
                if shore {
                    f *= 1.15;
                }
            }
            let c = |v: u8| ((v as f32 * f).round().clamp(0.0, 255.0)) as u8;
            px.push(egui::Color32::from_rgb(c(r), c(g), c(b)));
        }
    }
    egui::ColorImage::new([w, h], px)
}
