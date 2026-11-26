//! The throng drawn (docs/ATTENTION_BUDGET.md, "Built: the player side"): whom my character sees
//! but does not keep track of, as the authority counts them in `seen_throng` (one row per 6 m
//! cell, or per 12 m square of four far cells merged; at most 48). Only while the world's laws
//! let players heed (`heed_on` and `heed_players`: the set in place has the table, `net::throng`)
//! and the throng is drawn in Settings (`Prefs::throng`, on by default). Off, nothing here spawns
//! or draws anything.
//!
//! **The figures.** Each row gives `count` simple, unnamed figure cards (flat, unlit, upright,
//! turned to the camera; the look of the E1b mock on `attention-e1`), scattered round the cell's
//! centre on a sunflower spiral within half its `spread` (the members' widest extent), never
//! outside the square. A row's shares pick the poses: `fighting` cards hold a spear forward,
//! then `moving` cards walk, mirrored to the side `heading` points and stepping along it, and the
//! rest stand. `kinds` picks a person card or an animal stand-in (one bit: all of that kind;
//! several: shared out in turn, since the row has no count per kind). The fallen are no row: they
//! stay the game's own remains.
//!
//! **No colours.** A row carries no colour or outfit (an E1b finding: a real row would need a
//! colour summary). Until the authority sends one, every card is one neutral placeholder tint
//! ([`PLACEHOLDER`]); [`tops`] is where the summary will be read, and the coloured card
//! ([`person_image`] with a top colour) is ready for it. No colour is made up here.
//!
//! **No pops.** Cards are kept per square (`(cell, size)`, as the authority writes a row in place
//! when a field changes): a changed row moves its cards to their new places, a new card fades in
//! and a card no longer counted fades out, over the times people fade in and out of sight
//! (`fade.rs`), so someone moving between my individuals and the throng crossfades.
//!
//! Rings on the ground mark whom I keep track of (`heed.rs`): pins and my focus.

use crate::net::Net;
use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use living_bindings::SeenThrong;
use std::collections::BTreeMap;

/// A cell's side (m), as the authority's `throng::CELL_M`.
pub const CELL_M: f32 = 6.0;
/// `heading` when most stand or their ways cancel.
pub const STILL: u8 = 255;
/// `kinds` bits.
pub const PEOPLE: u8 = 1;
pub const WOLVES: u8 = 2;
pub const DEER: u8 = 4;
pub const OTHERS: u8 = 8;
/// A person card's size (m).
const CARD: (f32, f32) = (0.9, 1.8);
/// An animal stand-in's card (m).
const BEAST: (f32, f32) = (1.3, 0.95);
/// Fade in and out (s): as people do (`fade::IN_S`, `fade::OUT_S`), so a person leaving my
/// individuals for the throng crossfades with their card.
const IN_S: f32 = crate::fade::IN_S;
const OUT_S: f32 = crate::fade::OUT_S;
/// How fast a card walks to its new place when its row changes (m/s).
const GLIDE_MPS: f32 = 3.0;
/// The tint while rows carry no colour: one neutral slate, clearly a placeholder.
pub const PLACEHOLDER: [u8; 3] = [126, 132, 146];
/// The placeholder's head and legs: a little lighter and darker than the body, for legibility.
const PLACEHOLDER_HEAD: [u8; 3] = [170, 174, 184];
const PLACEHOLDER_LEGS: [u8; 3] = [84, 88, 100];
/// The coloured card's skin, trousers and spear (E1b), for when a row carries colours.
const SKIN: [u8; 3] = [214, 170, 138];
const TROUSERS: [u8; 3] = [52, 48, 58];
const SPEAR: [u8; 3] = [120, 92, 60];
/// The key light's illuminance by day (the island's noon, `assets/envs/island.json`): cards are
/// unlit, so they are shaded by the light's colour and its share of this ([`shade`]).
const DAY_LUX: f32 = 9000.0;
/// The darkest the shading goes (the island's night is about 0.3 of noon).
const NIGHT_SHADE: f32 = 0.3;
/// A crowd card is under the cursor's ground point within this (m).
const PICK_M: f32 = 0.9;

/// What a card shows.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub enum Pose {
    Stand,
    Walk,
    Fight,
}

/// What kind of creature a card stands for.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub enum Kind {
    Person,
    Wolf,
    Deer,
    Other,
}

/// One `seen_throng` row, decoded.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Row {
    pub id: u64,
    /// The square's top-left cell (map cells of [`CELL_M`]).
    pub cx: u32,
    pub cy: u32,
    /// 1, or 2 for four far cells merged.
    pub size: u8,
    pub count: u16,
    pub spread: u8,
    pub heading: u8,
    pub moving: u16,
    pub fighting: u16,
    pub kinds: u8,
}

impl Row {
    pub fn of(r: &SeenThrong) -> Row {
        Row { id: r.id, cx: r.cell >> 16, cy: r.cell & 0xFFFF, size: r.size.max(1), count: r.count, spread: r.spread, heading: r.heading, moving: r.moving, fighting: r.fighting, kinds: r.kinds }
    }

    /// How a client keys a row: by its square, as the authority updates a row in place.
    pub fn key(&self) -> (u32, u8) {
        ((self.cx << 16) | self.cy, self.size)
    }

    /// The square's side (m).
    pub fn side(&self) -> f32 {
        self.size as f32 * CELL_M
    }

    /// Its top-left corner (map m: x east, y south).
    pub fn origin(&self) -> Vec2 {
        Vec2::new(self.cx as f32, self.cy as f32) * CELL_M
    }

    pub fn centre(&self) -> Vec2 {
        self.origin() + Vec2::splat(self.side() * 0.5)
    }

    /// Whether a map point lies in the square.
    pub fn holds(&self, p: Vec2) -> bool {
        let (o, s) = (self.origin(), self.side());
        p.x >= o.x && p.y >= o.y && p.x < o.x + s && p.y < o.y + s
    }

    /// The way most move (map axes, unit), or none: still or mixed.
    pub fn heading_dir(&self) -> Option<Vec2> {
        heading_dir(self.heading)
    }

    /// The kinds present, in a fixed order.
    pub fn kinds_list(&self) -> Vec<Kind> {
        kinds_of(self.kinds)
    }

    /// Each card's pose: the fighting share first, then the moving share (those fighting are
    /// not counted twice), then the rest standing.
    pub fn poses(&self) -> Vec<Pose> {
        poses(self.count, self.moving, self.fighting)
    }
}

/// `heading` as a unit vector in map axes (x east, y south): 0 east, then clockwise in 45° steps
/// (2 south, 4 west, 6 north); 255 (or any value past 7) none.
pub fn heading_dir(h: u8) -> Option<Vec2> {
    (h != STILL && h < 8).then(|| Vec2::from_angle(h as f32 * std::f32::consts::FRAC_PI_4))
}

/// `kinds` bits as kinds, people first; none set reads as people (a row counts someone).
pub fn kinds_of(bits: u8) -> Vec<Kind> {
    let v: Vec<Kind> = [(PEOPLE, Kind::Person), (WOLVES, Kind::Wolf), (DEER, Kind::Deer), (OTHERS, Kind::Other)].into_iter().filter(|(b, _)| bits & b != 0).map(|(_, k)| k).collect();
    if v.is_empty() { vec![Kind::Person] } else { v }
}

/// `count` poses: `fighting` fight, then up to `moving` walk, the rest stand (shares clamped to
/// the count, as all three are rounded to 5 apart).
pub fn poses(count: u16, moving: u16, fighting: u16) -> Vec<Pose> {
    let n = count as usize;
    let f = (fighting as usize).min(n);
    let w = (moving as usize).min(n - f);
    let mut v = vec![Pose::Fight; f];
    v.extend(std::iter::repeat_n(Pose::Walk, w));
    v.extend(std::iter::repeat_n(Pose::Stand, n - f - w));
    v
}

/// Where a row's cards stand (map m): `n` places round the square's centre on a sunflower
/// spiral, within half the row's `spread`, but at least far enough apart to tell cards apart
/// (about 0.35 m × √n) and never outside the square. The same row gives the same places.
pub fn places(row: &Row, n: usize) -> Vec<Vec2> {
    let half = row.side() * 0.5;
    let r = (row.spread as f32 * 0.5).max(0.35 * (n as f32).sqrt()).max(0.5).min(half - 0.3);
    let c = row.centre();
    // A turn of the spiral per square, so neighbouring squares don't line up.
    let turn = ((row.cx.wrapping_mul(7) ^ row.cy.wrapping_mul(13)) % 97) as f32;
    (0..n)
        .map(|k| {
            let t = ((k as f32 + 0.5) / n.max(1) as f32).sqrt();
            let a = k as f32 * 2.399_963 + turn;
            let p = c + Vec2::new(a.cos(), a.sin()) * r * t;
            p.clamp(row.origin() + Vec2::splat(0.2), row.origin() + Vec2::splat(row.side() - 0.2))
        })
        .collect()
}

/// Each card's top colour, from the row. Rows carry none yet (the authority's gap, reported):
/// every card takes the placeholder. When `seen_throng` gains its colour summary, it is read here.
pub fn tops(_row: &Row, n: usize) -> Vec<Option<[u8; 3]>> {
    vec![None; n]
}

/// How an unlit card is shaded under the scene's light: the key light's colour (sRGB) times its
/// share of the day's illuminance, at least [`NIGHT_SHADE`]; full white without an atmosphere.
pub fn shade(atmo: Option<&crate::daylight::Atmo>) -> Vec3 {
    match atmo.filter(|a| a.active) {
        Some(a) => Vec3::from(a.light) * (a.lux / DAY_LUX).clamp(NIGHT_SHADE, 1.0),
        None => Vec3::ONE,
    }
}

/// One card drawn.
struct Card {
    entity: Entity,
    blob: Entity,
    mat: Handle<StandardMaterial>,
    pose: Pose,
    kind: Kind,
    top: Option<[u8; 3]>,
    /// Where it stands now and where it is going (map m).
    at: Vec2,
    to: Vec2,
    /// Drawn (0 gone, 1 full) and toward which.
    alpha: f32,
    target: f32,
    /// A number of its own, for its stepping.
    seed: f32,
}

/// A square's cards and the row they show.
struct Square {
    row: Row,
    cards: Vec<Card>,
}

/// The throng as drawn, for the dump, `heed.rs`'s picks and the drawing.
#[derive(Resource, Default)]
pub struct Throng {
    /// The rows taken this frame (none while the throng is not drawn).
    pub rows: Vec<Row>,
    /// Whether the set in place has my throng (heed for players on), and whether it is drawn.
    pub on: bool,
    pub drawn: bool,
    squares: BTreeMap<(u32, u8), Square>,
    /// Cards fading out after their square went.
    leaving: Vec<Card>,
}

impl Throng {
    /// The square of a card standing within [`PICK_M`] of a ground point (map m), and that card's
    /// place: a click on a crowd figure (`heed.rs`).
    pub fn card_at(&self, ground: Vec2) -> Option<(Row, Vec2)> {
        self.squares
            .values()
            .flat_map(|s| s.cards.iter().filter(|c| c.target > 0.5).map(move |c| (s.row, c.at, c.at.distance(ground))))
            .filter(|(_, _, d)| *d < PICK_M)
            .min_by(|a, b| a.2.total_cmp(&b.2))
            .map(|(r, at, _)| (r, at))
    }

    /// The dump's view: each row with the cards drawn for it.
    pub fn json(&self) -> serde_json::Value {
        let rows: Vec<serde_json::Value> = self
            .squares
            .values()
            .map(|s| {
                let live: Vec<&Card> = s.cards.iter().filter(|c| c.target > 0.5).collect();
                let n = |p: Pose| live.iter().filter(|c| c.pose == p).count();
                let k = |x: Kind| live.iter().filter(|c| c.kind == x).count();
                let r = &s.row;
                serde_json::json!({
                    "id": r.id, "cell": [r.cx, r.cy], "size": r.size, "count": r.count, "spread": r.spread, "heading": r.heading,
                    "moving": r.moving, "fighting": r.fighting, "kinds": r.kinds,
                    "cards": live.len(), "stand": n(Pose::Stand), "walk": n(Pose::Walk), "fight": n(Pose::Fight),
                    "people": k(Kind::Person), "animals": live.len() - k(Kind::Person),
                    "inside": live.iter().all(|c| r.holds(c.to)),
                    "tinted": live.iter().filter(|c| c.top.is_some()).count(),
                })
            })
            .collect();
        serde_json::json!({
            "on": self.on, "drawn": self.drawn, "rows": self.rows.len(),
            "count": self.rows.iter().map(|r| r.count as u64).sum::<u64>(),
            "cards": self.squares.values().map(|s| s.cards.iter().filter(|c| c.target > 0.5).count()).sum::<usize>(),
            "leaving": self.leaving.len() + self.squares.values().map(|s| s.cards.iter().filter(|c| c.target < 0.5).count()).sum::<usize>(),
            "tint": "placeholder",
            "squares": rows,
        })
    }
}

/// The shared meshes and textures.
#[derive(Resource)]
struct Kit {
    card: Handle<Mesh>,
    beast: Handle<Mesh>,
    blob: Handle<Mesh>,
    ring: Handle<Mesh>,
    blob_mat: Handle<StandardMaterial>,
    /// Ring materials: a pin, my focus.
    pin_mat: Handle<StandardMaterial>,
    focus_mat: Handle<StandardMaterial>,
    /// Textures by (kind, pose, top colour; none the placeholder).
    tex: BTreeMap<(Kind, Pose, Option<[u8; 3]>), Handle<Image>>,
}

/// Rings under whom I keep track of.
#[derive(Component)]
struct Ring;

pub struct ThrongPlugin;

impl Plugin for ThrongPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Throng>()
            .add_systems(Update, (take, draw, rings).chain().in_set(crate::phase::Phase::Camera).after(crate::camera::follow));
    }
}

fn soft(w: u32, h: u32, alpha: impl Fn(f32, f32) -> f32) -> Image {
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for j in 0..h {
        for i in 0..w {
            let a = alpha((i as f32 + 0.5) / w as f32, 1.0 - (j as f32 + 0.5) / h as f32).clamp(0.0, 1.0);
            px.extend_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: w, height: h, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

fn edge(d: f32) -> f32 {
    (0.5 - d / 0.03).clamp(0.0, 1.0)
}

/// Distance from a point to a segment, less a radius (m).
fn seg(p: Vec2, a: Vec2, b: Vec2, r: f32) -> f32 {
    let ab = b - a;
    let t = ((p - a).dot(ab) / ab.length_squared()).clamp(0.0, 1.0);
    (p - (a + ab * t)).length() - r
}

/// Which part of a person card a point is (0 none, 1 head, 2 top and arms, 3 legs, 4 spear) and
/// its distance outside it (m); u across, v up. The E1b mock's standing and fighting figures,
/// and a walking one (legs in stride, arms swinging; facing +u).
fn person_part(u: f32, v: f32, pose: Pose) -> (u8, f32) {
    let p = Vec2::new((u - 0.5) * CARD.0, v * CARD.1);
    let (head, top, legs, spear) = match pose {
        Pose::Fight => (
            (p - Vec2::new(0.06, 1.5)).length() - 0.12,
            seg(p, Vec2::new(-0.02, 0.88), Vec2::new(0.04, 1.3), 0.17).min(seg(p, Vec2::new(0.16, 1.28), Vec2::new(0.34, 1.12), 0.05)).min(seg(p, Vec2::new(-0.16, 1.28), Vec2::new(-0.3, 1.02), 0.05)),
            seg(p, Vec2::new(-0.08, 0.88), Vec2::new(-0.3, 0.04), 0.065).min(seg(p, Vec2::new(0.08, 0.88), Vec2::new(0.28, 0.04), 0.065)),
            seg(p, Vec2::new(-0.4, 0.75), Vec2::new(0.44, 1.72), 0.022),
        ),
        Pose::Walk => (
            (p - Vec2::new(0.04, 1.56)).length() - 0.12,
            seg(p, Vec2::new(0.0, 0.92), Vec2::new(0.03, 1.35), 0.17).min(seg(p, Vec2::new(-0.16, 1.34), Vec2::new(-0.3, 0.98), 0.05)).min(seg(p, Vec2::new(0.18, 1.34), Vec2::new(0.3, 1.0), 0.05)),
            seg(p, Vec2::new(-0.06, 0.9), Vec2::new(-0.26, 0.04), 0.065).min(seg(p, Vec2::new(0.06, 0.9), Vec2::new(0.24, 0.06), 0.065)),
            f32::MAX,
        ),
        Pose::Stand => (
            (p - Vec2::new(0.0, 1.58)).length() - 0.12,
            seg(p, Vec2::new(0.0, 0.92), Vec2::new(0.0, 1.36), 0.17).min(seg(p, Vec2::new(-0.2, 1.36), Vec2::new(-0.24, 0.9), 0.05)).min(seg(p, Vec2::new(0.2, 1.36), Vec2::new(0.24, 0.9), 0.05)),
            seg(p, Vec2::new(-0.08, 0.9), Vec2::new(-0.1, 0.04), 0.065).min(seg(p, Vec2::new(0.08, 0.9), Vec2::new(0.1, 0.04), 0.065)),
            f32::MAX,
        ),
    };
    [(1u8, head), (2, top), (3, legs), (4, spear)].into_iter().fold((0u8, f32::MAX), |a, b| if b.1 < a.1 { b } else { a })
}

/// An animal stand-in (u across, v up; facing +u): a body, a head, four legs; the pose moves the
/// legs (a stride walking or fighting).
fn beast_part(u: f32, v: f32, pose: Pose, kind: Kind) -> f32 {
    let p = Vec2::new((u - 0.5) * BEAST.0, v * BEAST.1);
    let tall = if kind == Kind::Deer { 0.12 } else { 0.0 };
    let body = seg(p, Vec2::new(-0.36, 0.5 + tall), Vec2::new(0.3, 0.52 + tall), 0.15);
    let head = (p - Vec2::new(0.46, 0.66 + tall * 1.8)).length() - 0.1;
    let neck = seg(p, Vec2::new(0.3, 0.55 + tall), Vec2::new(0.44, 0.64 + tall * 1.8), 0.05);
    let s = if pose == Pose::Stand { 0.0 } else { 0.1 };
    let legs = [(-0.3, -s), (-0.22, s), (0.2, -s), (0.28, s)].into_iter().map(|(x, d)| seg(p, Vec2::new(x, 0.45 + tall), Vec2::new(x + d, 0.03), 0.04)).fold(f32::MAX, f32::min);
    let tail = seg(p, Vec2::new(-0.48, 0.56 + tall), Vec2::new(-0.6, 0.4 + tall), 0.03);
    body.min(head).min(neck).min(legs).min(tail)
}

/// A card's texture: a person in the placeholder tint, or with a top colour (skin, the top,
/// dark trousers, a spear when fighting: E1b's coloured card), or an animal stand-in.
fn card_image(kind: Kind, pose: Pose, top: Option<[u8; 3]>) -> Image {
    let (w, h) = if kind == Kind::Person { (54u32, 108u32) } else { (78u32, 57u32) };
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for j in 0..h {
        for i in 0..w {
            let (u, v) = ((i as f32 + 0.5) / w as f32, 1.0 - (j as f32 + 0.5) / h as f32);
            let (c, d) = if kind == Kind::Person {
                let (part, d) = person_part(u, v, pose);
                let c = match (top, part) {
                    (Some(_), 1) => SKIN,
                    (Some(t), 2) => t,
                    (Some(_), 3) => TROUSERS,
                    (_, 4) => SPEAR,
                    (None, 1) => PLACEHOLDER_HEAD,
                    (None, 3) => PLACEHOLDER_LEGS,
                    _ => top.unwrap_or(PLACEHOLDER),
                };
                (c, d)
            } else {
                (top.unwrap_or(PLACEHOLDER_LEGS), beast_part(u, v, pose, kind))
            };
            let a = edge(d);
            // Edge pixels darker: a soft outline, so neighbouring cards stay apart.
            let k = if a < 0.99 { 0.55 } else { 1.0 };
            px.extend_from_slice(&[(c[0] as f32 * k) as u8, (c[1] as f32 * k) as u8, (c[2] as f32 * k) as u8, (a * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: w, height: h, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

/// The kit, made the first time a throng is drawn.
fn kit(meshes: &mut Assets<Mesh>, images: &mut Assets<Image>, mats: &mut Assets<StandardMaterial>) -> Kit {
    let blob_tex = images.add(soft(48, 48, |u, v| {
        let a = (1.0 - Vec2::new(u - 0.5, v - 0.5).length() * 2.0).clamp(0.0, 1.0);
        a * a * (3.0 - 2.0 * a)
    }));
    let ring_tex = images.add(soft(64, 64, |u, v| if (0.78..=1.0).contains(&(Vec2::new(u - 0.5, v - 0.5).length() * 2.0)) { 1.0 } else { 0.0 }));
    let ring = |c: [f32; 3], mats: &mut Assets<StandardMaterial>| mats.add(StandardMaterial { base_color: Color::srgba(c[0], c[1], c[2], 0.95), base_color_texture: Some(ring_tex.clone()), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 60.0, ..default() });
    Kit {
        card: meshes.add(Rectangle::new(CARD.0, CARD.1)),
        beast: meshes.add(Rectangle::new(BEAST.0, BEAST.1)),
        blob: meshes.add(Circle::new(0.5)),
        ring: meshes.add(Circle::new(1.0)),
        blob_mat: mats.add(StandardMaterial { base_color: Color::srgba(0.08, 0.08, 0.12, 0.3), base_color_texture: Some(blob_tex), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 40.0, ..default() }),
        pin_mat: ring([0.15, 0.95, 0.35], mats),
        focus_mat: ring([1.0, 0.72, 0.15], mats),
        tex: BTreeMap::new(),
    }
}

/// This frame's rows, from the set in place (`net::throng`); none while not drawn.
fn take(net: NonSend<Net>, prefs: Res<crate::keys::Prefs>, mut t: ResMut<Throng>) {
    let on = net.conn.as_ref().is_some_and(|c| c.throng_table());
    t.on = on;
    t.drawn = on && prefs.throng;
    t.rows = match net.conn.as_ref().filter(|_| t.drawn) {
        Some(c) => {
            let mut v: Vec<Row> = crate::net::throng(c).iter().map(Row::of).collect();
            v.sort_by_key(|r| r.key());
            v
        }
        None => Vec::new(),
    };
}

fn ground(island: Option<&crate::island::Island>, scene: &crate::world::Scene, p: Vec2) -> Vec3 {
    match island {
        Some(i) => Vec3::new(p.x, i.foot_height(p.x, p.y), p.y),
        None => scene.at3(p.x, p.y),
    }
}

/// Spawn, update in place and fade the cards, and turn them to the camera.
#[allow(clippy::too_many_arguments)]
fn draw(
    mut commands: Commands,
    mut t: ResMut<Throng>,
    kit_res: Option<ResMut<Kit>>,
    scene: NonSend<crate::world::Scene>,
    island: Option<Res<crate::island::Island>>,
    cam: Res<crate::camera::Cam>,
    time: Res<Time>,
    (mut meshes, mut images, mut mats): (ResMut<Assets<Mesh>>, ResMut<Assets<Image>>, ResMut<Assets<StandardMaterial>>),
    mut tfs: Query<&mut Transform>,
    atmo: Option<Res<crate::daylight::Atmo>>,
) {
    if t.rows.is_empty() && t.squares.is_empty() && t.leaving.is_empty() {
        return;
    }
    let mut kit = match kit_res {
        Some(k) => k,
        None => {
            commands.insert_resource(kit(&mut meshes, &mut images, &mut mats));
            return;
        }
    };
    let dt = time.delta_secs();
    let now = time.elapsed_secs();
    let t = &mut *t;
    // Rows to squares: a row's square keeps its cards; its count, poses and kinds are dealt
    // to them in a fixed order, so an unchanged row moves nothing.
    let mut seen: Vec<(u32, u8)> = Vec::with_capacity(t.rows.len());
    for row in t.rows.clone() {
        let key = row.key();
        seen.push(key);
        let sq = t.squares.entry(key).or_insert_with(|| Square { row, cards: Vec::new() });
        sq.row = row;
        let n = row.count as usize;
        let to = places(&row, n);
        let poses = row.poses();
        let kinds = row.kinds_list();
        let top = tops(&row, n);
        // Cards past the count fade out (in place); the rest are dealt their place and pose.
        for (k, c) in sq.cards.iter_mut().enumerate() {
            if k >= n {
                c.target = 0.0;
            }
        }
        for k in 0..n {
            let (pose, kind) = (poses[k], kinds[k % kinds.len()]);
            if k < sq.cards.len() {
                let c = &mut sq.cards[k];
                c.to = to[k];
                c.target = 1.0;
                if (c.pose, c.kind, c.top) != (pose, kind, top[k]) {
                    c.pose = pose;
                    c.kind = kind;
                    c.top = top[k];
                    let tex = kit.tex.entry((kind, pose, top[k])).or_insert_with(|| images.add(card_image(kind, pose, top[k]))).clone();
                    if let Some(mut m) = mats.get_mut(&c.mat) {
                        m.base_color_texture = Some(tex);
                    }
                }
                continue;
            }
            let tex = kit.tex.entry((kind, pose, top[k])).or_insert_with(|| images.add(card_image(kind, pose, top[k]))).clone();
            let mat = mats.add(StandardMaterial { base_color: Color::srgba(1.0, 1.0, 1.0, 0.0), base_color_texture: Some(tex), unlit: true, alpha_mode: AlphaMode::Blend, cull_mode: None, ..default() });
            let mesh = if kind == Kind::Person { kit.card.clone() } else { kit.beast.clone() };
            let base = ground(island.as_deref(), &scene, to[k]);
            let entity = commands.spawn((Mesh3d(mesh), MeshMaterial3d(mat.clone()), Transform::from_translation(base), Visibility::Visible, bevy::light::NotShadowCaster, Name::new("throng card"))).id();
            let blob = commands
                .spawn((Mesh3d(kit.blob.clone()), MeshMaterial3d(kit.blob_mat.clone()), Transform::from_translation(base + Vec3::Y * 0.05).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::ZERO), Visibility::Visible, bevy::light::NotShadowCaster))
                .id();
            let seed = (row.cx.wrapping_mul(31) ^ row.cy.wrapping_mul(17)).wrapping_add(k as u32 * 7) as f32 * 0.618;
            sq.cards.push(Card { entity, blob, mat, pose, kind, top: top[k], at: to[k], to: to[k], alpha: 0.0, target: 1.0, seed });
        }
    }
    // Squares no longer in the rows: their cards fade out.
    let gone: Vec<(u32, u8)> = t.squares.keys().filter(|k| !seen.contains(k)).copied().collect();
    for k in gone {
        if let Some(sq) = t.squares.remove(&k) {
            t.leaving.extend(sq.cards.into_iter().map(|mut c| {
                c.target = 0.0;
                c.to = c.at;
                c
            }));
        }
    }
    let lit = shade(atmo.as_deref());
    let eye = cam.pose.translation();
    let right = cam.pose.right().as_vec3();
    let mut step = |c: &mut Card, heading: Option<Vec2>| -> bool {
        // Fade toward its target.
        let rate = if c.target > c.alpha { dt / IN_S } else { dt / OUT_S };
        c.alpha = if c.target > c.alpha { (c.alpha + rate).min(c.target) } else { (c.alpha - rate).max(c.target) };
        c.at = c.at.move_towards(c.to, GLIDE_MPS * dt);
        // Walking steps along the way; fighting lunges a little; standing keeps still.
        let (sway, lift) = match (c.pose, heading) {
            (Pose::Walk, Some(h)) => (h * 0.25 * (now * 1.7 + c.seed).sin(), 0.04 * (now * 7.0 + c.seed).sin().abs()),
            (Pose::Fight, _) => (heading.unwrap_or(Vec2::X) * 0.08 * (now * 3.1 + c.seed).sin(), 0.0),
            _ => (Vec2::ZERO, 0.0),
        };
        let p = c.at + sway;
        let base = ground(island.as_deref(), &scene, p);
        let half = if c.kind == Kind::Person { CARD.1 * 0.5 } else { BEAST.1 * 0.5 };
        let yaw = (eye.x - base.x).atan2(eye.z - base.z);
        // Mirrored to face the way it walks, as the camera sees it.
        let face = heading.map(|h| Vec3::new(h.x, 0.0, h.y)).filter(|_| c.pose != Pose::Stand);
        let flip = if face.is_some_and(|f| f.dot(right) < 0.0) { -1.0 } else { 1.0 };
        if let Ok(mut tf) = tfs.get_mut(c.entity) {
            *tf = Transform::from_translation(base + Vec3::Y * (half + lift)).with_rotation(Quat::from_rotation_y(yaw)).with_scale(Vec3::new(flip, 1.0, 1.0));
        }
        if let Ok(mut tf) = tfs.get_mut(c.blob) {
            tf.translation = base + Vec3::Y * 0.05;
            tf.scale = Vec3::splat(c.alpha * if c.kind == Kind::Person { 0.9 } else { 1.2 });
        }
        if let Some(mut m) = mats.get_mut(&c.mat) {
            let want = Color::srgba(lit.x, lit.y, lit.z, c.alpha * 0.95);
            let (h, w) = (m.base_color.to_srgba(), want.to_srgba());
            if (h.alpha - w.alpha).abs() > 0.004 || (h.red - w.red).abs() > 0.01 || (h.green - w.green).abs() > 0.01 || (h.blue - w.blue).abs() > 0.01 {
                m.base_color = want;
            }
        }
        // Gone: fully faded out.
        c.target <= 0.0 && c.alpha <= 0.0
    };
    let mut dead: Vec<Card> = Vec::new();
    for sq in t.squares.values_mut() {
        let h = sq.row.heading_dir();
        let mut k = 0;
        while k < sq.cards.len() {
            if step(&mut sq.cards[k], h) && k >= sq.row.count as usize {
                dead.push(sq.cards.remove(k));
            } else {
                k += 1;
            }
        }
    }
    let mut k = 0;
    while k < t.leaving.len() {
        if step(&mut t.leaving[k], None) {
            dead.push(t.leaving.swap_remove(k));
        } else {
            k += 1;
        }
    }
    for c in dead {
        commands.entity(c.entity).despawn();
        commands.entity(c.blob).despawn();
        mats.remove(&c.mat);
    }
}

/// Rings on the ground under whom I keep track of: green under a pin, amber under my focus.
/// Only while heed for players is on.
#[allow(clippy::too_many_arguments)]
fn rings(
    mut commands: Commands,
    heed: Option<Res<crate::heed::Heed>>,
    kit: Option<Res<Kit>>,
    scene: NonSend<crate::world::Scene>,
    island: Option<Res<crate::island::Island>>,
    (mut meshes, mut images, mut mats): (ResMut<Assets<Mesh>>, ResMut<Assets<Image>>, ResMut<Assets<StandardMaterial>>),
    q: Query<Entity, With<Ring>>,
) {
    let marks: Vec<(u32, bool)> = heed.as_ref().filter(|h| h.on).map(|h| h.marks()).unwrap_or_default();
    let had = !q.is_empty();
    if marks.is_empty() && !had {
        return;
    }
    for e in &q {
        commands.entity(e).despawn();
    }
    if marks.is_empty() {
        return;
    }
    let Some(kit) = kit else {
        commands.insert_resource(self::kit(&mut meshes, &mut images, &mut mats));
        return;
    };
    for (id, focus) in marks {
        let Some((p, _)) = scene.shown.get(&id) else { continue };
        let at = ground(island.as_deref(), &scene, *p) + Vec3::Y * 0.07;
        let mat = if focus { kit.focus_mat.clone() } else { kit.pin_mat.clone() };
        let r = if focus { 0.85 } else { 0.7 };
        commands.spawn((Ring, Mesh3d(kit.ring.clone()), MeshMaterial3d(mat), Transform::from_translation(at).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::splat(r)), Visibility::Visible, bevy::light::NotShadowCaster));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use spacetimedb_sdk::Identity;

    fn row(cell: u32, size: u8, count: u16, spread: u8, heading: u8, moving: u16, fighting: u16, kinds: u8) -> SeenThrong {
        SeenThrong { id: 9, viewer: Identity::ZERO, cell, size, count, spread, heading, moving, fighting, kinds }
    }

    #[test]
    fn a_row_decodes_its_cell_heading_and_kinds() {
        // x 401.5 m, y 255 m: cell (66, 42), the authority's (x / 6) << 16 | (y / 6).
        let r = Row::of(&row((66 << 16) | 42, 1, 7, 4, 2, 3, 2, PEOPLE | WOLVES));
        assert_eq!((r.cx, r.cy, r.size), (66, 42, 1));
        assert_eq!(r.origin(), Vec2::new(396.0, 252.0));
        assert_eq!(r.centre(), Vec2::new(399.0, 255.0));
        assert!(r.holds(Vec2::new(401.5, 255.0)) && !r.holds(Vec2::new(402.0, 255.0)));
        assert_eq!(r.key(), ((66 << 16) | 42, 1));
        // A merged square: 12 m from its top-left cell.
        let m = Row::of(&row((10 << 16) | 20, 2, 30, 10, STILL, 0, 0, PEOPLE));
        assert_eq!((m.side(), m.centre()), (12.0, Vec2::new(66.0, 126.0)));
        assert_ne!(m.key(), Row::of(&row((10 << 16) | 20, 1, 30, 10, STILL, 0, 0, PEOPLE)).key());
        // Headings: 0 east, clockwise (map y grows south): 2 south, 4 west, 6 north; 255 none.
        let near = |a: Vec2, b: Vec2| a.distance(b) < 1e-5;
        assert!(near(heading_dir(0).unwrap(), Vec2::X));
        assert!(near(heading_dir(2).unwrap(), Vec2::Y));
        assert!(near(heading_dir(4).unwrap(), -Vec2::X));
        assert!(near(heading_dir(6).unwrap(), -Vec2::Y));
        assert!(near(heading_dir(1).unwrap(), Vec2::new(1.0, 1.0).normalize()));
        assert_eq!(heading_dir(STILL), None);
        assert_eq!(heading_dir(8), None);
        // Kinds by bit, people first; none set reads as people.
        assert_eq!(r.kinds_list(), vec![Kind::Person, Kind::Wolf]);
        assert_eq!(kinds_of(DEER | OTHERS), vec![Kind::Deer, Kind::Other]);
        assert_eq!(kinds_of(0), vec![Kind::Person]);
    }

    #[test]
    fn poses_follow_the_row_s_shares() {
        let count = |v: &[Pose], p: Pose| v.iter().filter(|x| **x == p).count();
        let v = poses(10, 5, 3);
        assert_eq!((v.len(), count(&v, Pose::Fight), count(&v, Pose::Walk), count(&v, Pose::Stand)), (10, 3, 5, 2));
        // Quantized shares past the count are clamped (count 5, moving 5, fighting 5).
        let v = poses(5, 5, 5);
        assert_eq!((count(&v, Pose::Fight), count(&v, Pose::Walk)), (5, 0));
        let v = poses(4, 10, 0);
        assert_eq!(count(&v, Pose::Walk), 4);
        assert!(poses(0, 3, 3).is_empty());
    }

    #[test]
    fn cards_stand_within_the_spread_and_the_square() {
        for (size, count, spread) in [(1u8, 1u16, 0u8), (1, 5, 2), (1, 20, 4), (1, 30, 8), (2, 60, 16), (2, 3, 2), (1, 100, 12)] {
            let r = Row::of(&row((50 << 16) | 70, size, count, spread, STILL, 0, 0, PEOPLE));
            let ps = places(&r, count as usize);
            assert_eq!(ps.len(), count as usize);
            let reach = (spread as f32 * 0.5).max(0.35 * (count as f32).sqrt()).max(0.5) + 1e-3;
            for p in &ps {
                assert!(r.holds(*p), "{p} outside {r:?}");
                assert!(p.distance(r.centre()) <= reach, "{p} past the spread of {r:?}");
            }
            // The same row, the same places.
            assert_eq!(ps, places(&r, count as usize));
            // Apart enough to tell (no two on one spot), for counts that fit the square.
            if count > 1 {
                let min = ps.iter().enumerate().flat_map(|(i, a)| ps[i + 1..].iter().map(move |b| a.distance(*b))).fold(f32::MAX, f32::min);
                assert!(min > 0.05, "{count} cards in {size}: {min}");
            }
        }
        // A wide spread on a small square stays in the square.
        let r = Row::of(&row((1 << 16) | 1, 1, 6, 30, STILL, 0, 0, PEOPLE));
        assert!(places(&r, 6).iter().all(|p| r.holds(*p)));
    }

    #[test]
    fn cards_darken_with_the_light_but_not_to_nothing() {
        assert_eq!(shade(None), Vec3::ONE);
        let mut a = crate::daylight::Atmo { active: true, light: [1.0, 0.96, 0.88], lux: 9000.0, ..Default::default() };
        assert!((shade(Some(&a)) - Vec3::new(1.0, 0.96, 0.88)).length() < 1e-5);
        a.lux = 2800.0;
        a.light = [0.46, 0.6, 1.0];
        assert!((shade(Some(&a)) - Vec3::new(0.46, 0.6, 1.0) * (2800.0 / 9000.0)).length() < 1e-5);
        a.lux = 100.0;
        assert!((shade(Some(&a)) - Vec3::new(0.46, 0.6, 1.0) * NIGHT_SHADE).length() < 1e-5);
        a.active = false;
        assert_eq!(shade(Some(&a)), Vec3::ONE);
    }

    #[test]
    fn rows_carry_no_colour_so_every_card_is_the_placeholder() {
        let r = Row::of(&row(0, 1, 7, 4, STILL, 0, 0, PEOPLE));
        assert!(tops(&r, 7).iter().all(|t| t.is_none()));
    }
}
