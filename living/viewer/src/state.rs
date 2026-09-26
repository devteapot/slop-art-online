//! Per-frame snapshot of the hot tables and the viewer's persistent state and caches.

use crate::net::Net;
use bevy_egui::egui;
use living_bindings::*;
use crate::art::{Art, Season};
use crate::terrain::TerrainArt;
use living_rules::map::{Map, MAP_H, MAP_W};

static WORLD_DIMS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(((MAP_W as u64) << 32) | MAP_H as u64);

/// World size in tiles, from the `world` row (valley defaults until it arrives).
pub fn world_tiles() -> egui::Vec2 {
    let v = WORLD_DIMS.load(std::sync::atomic::Ordering::Relaxed);
    egui::vec2((v >> 32) as f32, (v & 0xffff_ffff) as f32)
}

fn set_world_tiles(w: u32, h: u32) {
    if w > 0 && h > 0 {
        WORLD_DIMS.store(((w as u64) << 32) | h as u64, std::sync::atomic::Ordering::Relaxed);
    }
}

/// Camp colours for the minimap and markers (index = camp), and the loner colour.
pub const CAMP_COLORS: [egui::Color32; 6] = [
    egui::Color32::from_rgb(236, 96, 84),
    egui::Color32::from_rgb(84, 164, 244),
    egui::Color32::from_rgb(244, 196, 64),
    egui::Color32::from_rgb(170, 120, 240),
    egui::Color32::from_rgb(90, 206, 146),
    egui::Color32::from_rgb(244, 140, 200),
];
pub const LONER: egui::Color32 = egui::Color32::from_rgb(235, 235, 235);

/// A community: a town or band from the characters' backgrounds, or (without
/// backgrounds) a cluster of nearby homes.
pub struct Community {
    pub name: String,
    pub kind: &'static str,
    pub home: egui::Pos2,
    pub members: Vec<u32>,
    pub color: egui::Color32,
}

/// Build communities from background JSON (town/band), assigning people without one to a
/// parent's community or the nearest home within 25 tiles; falls back to clustering homes
/// within 10 tiles when no backgrounds exist.
fn communities_of(chars: &HashMap<u32, Character>, backgrounds: &HashMap<u32, serde_json::Value>) -> (Vec<Community>, HashMap<u32, usize>) {
    let mut people: Vec<&Character> = chars.values().filter(|c| c.kind == "person").collect();
    people.sort_by_key(|c| c.id);
    let mut list: Vec<Community> = Vec::new();
    let mut of: HashMap<u32, usize> = HashMap::new();
    let pos = |v: &serde_json::Value| -> Option<egui::Pos2> {
        let a = v.as_array()?;
        Some(egui::pos2(a.first()?.as_f64()? as f32, a.get(1)?.as_f64()? as f32))
    };
    for c in &people {
        let Some(b) = backgrounds.get(&c.id) else { continue };
        let (name, kind, home) = if let Some(t) = b.get("town").and_then(|t| t.as_str()) {
            (t.to_string(), "town", b.get("town_center").and_then(pos))
        } else if let Some(t) = b.get("band").and_then(|t| t.as_str()) {
            (t.to_string(), "band", b.get("camp").and_then(pos))
        } else {
            continue;
        };
        let k = match list.iter().position(|x| x.name == name) {
            Some(k) => k,
            None => {
                list.push(Community { name, kind, home: home.unwrap_or(egui::pos2(c.home_x, c.home_y)), members: Vec::new(), color: egui::Color32::WHITE });
                list.len() - 1
            }
        };
        list[k].members.push(c.id);
        of.insert(c.id, k);
    }
    if list.is_empty() {
        // No backgrounds: cluster homes (union-find within 10 tiles).
        let n = people.len();
        let mut group: Vec<usize> = (0..n).collect();
        fn root(g: &mut [usize], mut i: usize) -> usize {
            while g[i] != i {
                g[i] = g[g[i]];
                i = g[i];
            }
            i
        }
        for i in 0..n {
            for j in i + 1..n {
                let d = ((people[i].home_x - people[j].home_x).powi(2) + (people[i].home_y - people[j].home_y).powi(2)).sqrt();
                if d <= 10.0 {
                    let (a, b) = (root(&mut group, i), root(&mut group, j));
                    group[a.max(b)] = a.min(b);
                }
            }
        }
        let mut by_root: Vec<(usize, Vec<usize>)> = Vec::new();
        for i in 0..n {
            let r = root(&mut group, i);
            match by_root.iter_mut().find(|(k, _)| *k == r) {
                Some((_, v)) => v.push(i),
                None => by_root.push((r, vec![i])),
            }
        }
        for (_, idx) in by_root.into_iter().filter(|(_, v)| v.len() >= 2) {
            let k = list.len();
            let home = idx.iter().fold(egui::Vec2::ZERO, |a, i| a + egui::vec2(people[*i].home_x, people[*i].home_y)) / idx.len() as f32;
            list.push(Community { name: format!("camp {}", k + 1), kind: "camp", home: home.to_pos2(), members: Vec::new(), color: egui::Color32::WHITE });
            for i in idx {
                list[k].members.push(people[i].id);
                of.insert(people[i].id, k);
            }
        }
    } else {
        // Newcomers without a background: a parent's community, else the nearest home.
        for c in &people {
            if of.contains_key(&c.id) {
                continue;
            }
            let via_parent = [c.parent_a, c.parent_b].iter().find_map(|p| of.get(p).copied());
            let nearest = list
                .iter()
                .enumerate()
                .map(|(k, x)| (k, (x.home - egui::pos2(c.home_x, c.home_y)).length()))
                .filter(|(_, d)| *d < 25.0)
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .map(|(k, _)| k);
            if let Some(k) = via_parent.or(nearest) {
                list[k].members.push(c.id);
                of.insert(c.id, k);
            }
        }
    }
    for (k, x) in list.iter_mut().enumerate() {
        x.color = CAMP_COLORS[k % CAMP_COLORS.len()];
    }
    (list, of)
}
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
    pub artifacts: Vec<Artifact>,
    /// Characters who know `writing`.
    pub literate: std::collections::HashSet<u32>,
    /// Characters carrying a torch.
    pub torches: std::collections::HashSet<u32>,
    pub trades: Vec<TradeOffer>,
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
            artifacts: c.db.artifact().iter().collect(),
            literate: c.db.know_how().iter().filter(|k| k.technique == "writing").map(|k| k.actor).collect(),
            torches: c.db.inventory().iter().filter(|i| i.item == "torch" && i.qty > 0 && i.owner < (1u64 << 32)).map(|i| i.owner as u32).collect(),
            trades: c.db.trade_offer().iter().collect(),
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

    pub fn season(&self) -> Season {
        thread_local! {
            static PREVIEW: Option<usize> = crate::clock::season_override();
        }
        let i = PREVIEW.with(|p| *p).unwrap_or_else(|| living_rules::season_of(self.now, self.epoch_ms(), self.day_ms()));
        Season::from_index(i)
    }

    /// Resource amount now; plants regrow only in growing (non-winter) time.
    pub fn resource_amount(&self, n: &ResourceNode) -> f32 {
        let grow = living_rules::growing_ms(n.at_ms, self.now, self.epoch_ms(), self.day_ms());
        (n.amount + n.regen * grow as f32 / 60000.0).min(n.max)
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
pub enum LeftTab {
    People,
    Communities,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum StoryFilter {
    All,
    LearningTrade,
}

/// Story kinds shown by the "Learning & trade" filter.
pub const LEARNING_TRADE: &[&str] = &["trade", "give", "learn", "write", "plant"];

/// Short-lived visual effects that the tables only imply (a finished throw or strike).
pub struct Effect {
    pub kind: EffectKind,
    pub from: egui::Pos2,
    pub to: u32,
    pub to_at: egui::Pos2,
    pub start_ms: u64,
    pub dur_ms: u64,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum EffectKind {
    Spear,
    Slash,
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
    /// Combat: last seen attack/throw per attacker, recent fights, spears in flight.
    pub combat: HashMap<u32, Activity>,
    pub fights: HashMap<(u32, u32), u64>,
    pub effects: Vec<Effect>,
    pub story_filter: StoryFilter,
    pub communities: Vec<Community>,
    pub community_of: HashMap<u32, usize>,
    pub backgrounds: HashMap<u32, serde_json::Value>,
    community_key: (u32, usize),
    pub left_tab: LeftTab,
    /// Chunk build budget per frame (ms) and the last frame's terrain stats.
    pub terrain_stats: (usize, usize, f32),
    /// Sign structure whose text is pinned open.
    pub open_sign: Option<u64>,
    last_selected: Option<u32>,
    pub terrain: Option<TerrainArt>,
    pub art: Option<Art>,
    /// Last horizontal facing per creature (true = left).
    pub facing: HashMap<u32, bool>,
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
    pub logged_at: u32,
    gens: (u32, u32, u32, u32),
    styled: bool,
}

impl Default for View {
    fn default() -> Self {
        Self {
            center: (world_tiles() / 2.0).to_pos2(),
            zoom: 8.0,
            fitted: false,
            selected: None,
            follow: false,
            tab: Tab::Identity,
            story_only_selected: false,
            exp_highlight: None,
            exp_scroll: false,
            open_sign: None,
            combat: HashMap::new(),
            fights: HashMap::new(),
            effects: Vec::new(),
            story_filter: StoryFilter::All,
            communities: Vec::new(),
            community_of: HashMap::new(),
            backgrounds: HashMap::new(),
            community_key: (u32::MAX, usize::MAX),
            left_tab: LeftTab::People,
            terrain_stats: (0, 0, 0.0),
            last_selected: None,
            terrain: None,
            art: None,
            facing: HashMap::new(),
            map: None,
            chronicle: Vec::new(),
            thoughts: HashMap::new(),
            thought_exps: HashMap::new(),
            shown: HashMap::new(),
            fps: 60.0,
            frame_ms: 0.0,
            logged_at: 0,
            gens: (u32::MAX, u32::MAX, u32::MAX, u32::MAX),
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
        if let Some(w) = &snap.world {
            let before = world_tiles();
            set_world_tiles(w.width, w.height);
            if world_tiles() != before {
                // A different world: rebuild the terrain at the new size and refit.
                self.gens.0 = u32::MAX;
                self.fitted = false;
            }
        }
        let gens = net.gens.get();
        if let Some(c) = &net.conn {
            if gens.0 != self.gens.0 {
                let chunks: Vec<(u32, Vec<u8>)> = c.db.terrain_chunk().iter().map(|r| (r.id, r.tiles)).collect();
                let dims = world_tiles();
                self.terrain = None;
                self.map = (!chunks.is_empty()).then(|| Map::from_chunks(dims.x as u32, dims.y as u32, chunks));
            }
            if gens.3 != self.gens.3 {
                self.backgrounds = c
                    .db
                    .background()
                    .iter()
                    .filter_map(|b| serde_json::from_str(&b.text).ok().map(|v| (b.id, v)))
                    .collect();
            }
            let key = (gens.3, snap.chars.len());
            if key != self.community_key {
                self.community_key = key;
                (self.communities, self.community_of) = communities_of(&snap.chars, &self.backgrounds);
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
        if self.art.is_none() {
            self.art = Some(Art::new(ctx));
        }
        let season = self.season(snap);
        match (&mut self.terrain, &self.map) {
            (Some(t), _) => t.set_season(ctx, season),
            (None, Some(map)) => self.terrain = Some(crate::terrain::TerrainArt::new(ctx, map.clone(), season)),
            _ => {}
        }
        for (id, b) in &snap.bodies {
            if b.vx.abs() > 0.05 && b.next_ms > snap.now {
                self.facing.insert(*id, b.vx < 0.0);
            }
        }
        self.track_combat(snap);
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

    /// Remember windups; when one ends (row gone or replaced) near its `ends_ms`, spawn the
    /// implied projectile or strike so the hit can be seen.
    fn track_combat(&mut self, snap: &Snap) {
        let now = snap.now;
        let mut ended = Vec::new();
        for (id, prev) in &self.combat {
            let still = snap.activity.get(id).is_some_and(|a| a.skill == prev.skill && a.victim == prev.victim && a.ends_ms == prev.ends_ms);
            if !still {
                ended.push(*id);
            }
        }
        for id in ended {
            let prev = self.combat.remove(&id).unwrap();
            if now + 400 < prev.ends_ms || now > prev.ends_ms + 1500 {
                continue; // cancelled early, or we were not watching
            }
            let (Some(from), Some(to_at)) = (self.shown.get(&id).copied(), self.shown.get(&prev.victim).copied()) else { continue };
            let (kind, dur) = if prev.skill == "throw" {
                (EffectKind::Spear, ((to_at - from).length() / 18.0 * 1000.0) as u64 + 60)
            } else {
                (EffectKind::Slash, 260)
            };
            self.effects.push(Effect { kind, from, to: prev.victim, to_at, start_ms: now, dur_ms: dur });
        }
        for (id, a) in &snap.activity {
            if a.victim != 0 && (a.skill == "attack" || a.skill == "throw") {
                self.combat.insert(*id, a.clone());
                let key = if *id < a.victim { (*id, a.victim) } else { (a.victim, *id) };
                self.fights.insert(key, now);
            }
        }
        self.fights.retain(|(a, b), t| now.saturating_sub(*t) < 5000 && snap.bodies.contains_key(a) && snap.bodies.contains_key(b));
        self.effects.retain(|e| now < e.start_ms + e.dur_ms + 200);
    }

    /// Midpoint of the most recent fight, if any.
    pub fn latest_fight(&self) -> Option<egui::Pos2> {
        let (&(a, b), _) = self.fights.iter().max_by_key(|(_, t)| **t)?;
        let (pa, pb) = (self.shown.get(&a)?, self.shown.get(&b)?);
        Some(pa.lerp(*pb, 0.5))
    }

    pub fn season(&self, snap: &Snap) -> Season {
        snap.season()
    }

    pub fn community_color(&self, id: u32) -> egui::Color32 {
        self.community_of.get(&id).map(|k| self.communities[*k].color).unwrap_or(LONER)
    }

    pub fn model_of(&self, id: u32) -> Option<&str> {
        self.thoughts.get(&id)?.iter().find(|t| !t.model.is_empty()).map(|t| t.model.as_str())
    }
}
