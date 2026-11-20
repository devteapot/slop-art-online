//! Hand-made character files (docs/HANDMADE_HAIR.md): what a standalone GLB declares in its glTF
//! extras, read the same way by the asset view and by live loading.
//!
//! - **The scene** (`scenes[scene].extras.slop`): `{"contract": 1, "character": "handmade",
//!   "forward": "+Z" | "-Z"}`. A `"+Z"` file's top nodes are turned half round when its scene
//!   spawns ([`on_ready`]), so every character file faces −Z in its root's frame (VRM's
//!   convention) and every place that turns a character's root stays as it is.
//! - **Each material** (`materials[i].extras.slop`): a `slot` (`hair`, `skin`, `face`, `eyes`,
//!   `tint`, `cloth`) that decides its kind instead of its name ([`kind_of`]), and on hair an
//!   optional profile (`hair`: four sRGB swatches, two thresholds, an edge and a feather;
//!   [`HairProfile`]), shaded by `toon.wesl` `hand_hair`.
//! - **The highlight mask:** the hair's `_HIGHLIGHT` per vertex, moved into its second UVs' y as
//!   1 + value ([`pack_highlight`]), or `<stem>.hair.png` (R, linear) beside the file, which wins.
//! - **Ink** (contract v1.2, docs/HANDMADE_INK.md): any material but a tint may carry `ink`
//!   ([`InkProfile`]), drawn from its ink map (`<stem>.<slot>.ink.png`, [`ink_map`]: G the
//!   distance to the nearest stroke, R its width) through the material's own light.
//!
//! Files without `slop` extras are untouched: nothing here applies to them.

use bevy::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};

use crate::style::{Kind, ToonParams};

/// The contract version this client reads (`slop.contract`).
pub const CONTRACT: u64 = 1;

/// A hair vertex's highlight mask (`_HIGHLIGHT`, 0 to 1; the highlight's edge is its 0.5
/// contour). The glTF loader reads it (main.rs); [`pack_highlight`] moves it into the second UVs.
pub const ATTRIBUTE_HIGHLIGHT: bevy::mesh::MeshVertexAttribute = bevy::mesh::MeshVertexAttribute::new("Highlight", 0x5c3e_9a04, bevy::render::render_resource::VertexFormat::Float32);

/// What a hand-made file's scene declares.
#[derive(Clone, Debug, PartialEq)]
pub struct Handmade {
    /// The face points along glTF +Z (else −Z) in the file's own frame.
    pub plus_z: bool,
    /// The scene's top nodes, by name: what [`on_ready`] turns for a `"+Z"` file.
    pub tops: Vec<String>,
}

/// Warn once per message.
pub fn warn_once(msg: String) {
    static SEEN: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();
    if SEEN.get_or_init(Default::default).lock().unwrap().insert(msg.clone()) {
        warn!("{msg}");
    }
}

/// The file's declaration, if it is a hand-made character file (cached; the JSON chunk only).
pub fn of(file: &str) -> Option<Handmade> {
    static CACHE: OnceLock<Mutex<HashMap<String, Option<Handmade>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(v) = cache.lock().unwrap().get(file) {
        return v.clone();
    }
    let v = crate::lookdev::glb_json(file).and_then(|j| scene_of(&j, file));
    cache.lock().unwrap().insert(file.to_string(), v.clone());
    v
}

/// A file's declaration from its glTF JSON; None (with a warning where the file tried) unless it
/// declares a hand-made character this client reads.
pub fn scene_of(j: &serde_json::Value, file: &str) -> Option<Handmade> {
    let scene = j["scene"].as_u64().unwrap_or(0) as usize;
    let s = j["scenes"].get(scene)?;
    let slop = s["extras"].get("slop")?;
    let contract = slop["contract"].as_u64();
    if contract.is_none_or(|c| c > CONTRACT) {
        warn_once(format!("handmade: {file}: contract {:?} is not one this client reads ({CONTRACT}); the file is drawn as before", slop["contract"]));
        return None;
    }
    match slop["character"].as_str() {
        Some("handmade") => {}
        None => return None,
        Some(other) => {
            warn_once(format!("handmade: {file}: character {other:?} is not known; the file is drawn as before"));
            return None;
        }
    }
    let plus_z = match slop["forward"].as_str() {
        Some("+Z") => true,
        Some("-Z") => false,
        f => {
            warn_once(format!("handmade: {file}: forward {f:?} is not \"+Z\" or \"-Z\"; taken as -Z"));
            false
        }
    };
    let tops = s["nodes"].as_array().into_iter().flatten().filter_map(|n| j["nodes"].get(n.as_u64()? as usize)?["name"].as_str().map(String::from)).collect();
    Some(Handmade { plus_z, tops })
}

/// A material's slot (`slop.slot`), read by its lowercase variant name (`"hair"`, `"tint"`, ...):
/// serde spells them, so the client's skill-name guard doesn't read the `face` slot as the skill.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Slot {
    Hair,
    Skin,
    Face,
    Eyes,
    Tint,
    Cloth,
}

/// A hand-made hair profile (`slop.hair`): swatches as sRGB bytes, thresholds on N·L.
#[derive(Clone, Debug, PartialEq)]
pub struct HairProfile {
    pub shade: [u8; 3],
    pub mid: [u8; 3],
    pub light: [u8; 3],
    pub highlight: [u8; 3],
    pub t1: f32,
    pub t2: f32,
    pub edge: f32,
    pub feather: f32,
    /// `highlight_map`: a mask texture's path under the asset folder, instead of the file's own
    /// `<stem>.hair.png`.
    pub highlight_map: Option<String>,
    /// Lock ink lines (v1.1, docs/HANDMADE_HAIR.md "Lock ink lines"): drawn only when the profile
    /// sets one of `ink`, `ink_px`, `ink_range`, `ink_fade_px` (`inked`) and the mask texture
    /// has a G channel. `ink`: the line's colour (default `shade` x 0.6 in linear).
    pub inked: bool,
    pub ink: Option<[u8; 3]>,
    pub ink_px: f32,
    pub ink_range: f32,
    pub ink_fade_px: f32,
}

pub const INK_PX: f32 = 1.25;
pub const INK_RANGE: f32 = 0.004;
pub const INK_FADE_PX: f32 = 3.0;

pub const T1: f32 = -0.20;
pub const T2: f32 = 0.40;
pub const EDGE: f32 = 0.02;
pub const FEATHER: f32 = 0.08;

impl Slot {
    /// The slot as a file spells it (`"eyes"`, ...), from its serde name.
    pub fn name(self) -> String {
        serde_json::to_value(self).ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default()
    }
}

/// How an ink line's width is set (`slop.ink.width`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InkWidth {
    /// A screen-pixel line from `px`, up to 4 x `px` close (the hair's).
    Px,
    /// A world-sized stroke: its half-width is the map's R x `range` in UV, at least `min_px`.
    Uv,
}

/// A material's ink (contract v1.2, docs/HANDMADE_INK.md, `slop.ink`).
#[derive(Clone, Debug, PartialEq)]
pub struct InkProfile {
    pub color: [u8; 3],
    pub width: InkWidth,
    pub px: f32,
    pub min_px: f32,
    pub range: f32,
    pub fade_px: f32,
    /// A path under the asset folder, instead of the slot's `<stem>.<slot>.ink.png`.
    pub map: Option<String>,
    /// In "px" mode: the map's R is the local width fraction.
    pub taper: bool,
}

pub const INK_MIN_PX: f32 = 1.0;

/// What a material's extras declare.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct MaterialSlop {
    pub slot: Option<Slot>,
    pub hair: Option<HairProfile>,
    pub ink: Option<InkProfile>,
}

/// A material's `slop` from its glTF extras (Bevy's `GltfMaterialExtras` JSON); `what` names it
/// in warnings.
pub fn material_of(extras: Option<&str>, what: &str) -> MaterialSlop {
    let Some(v) = extras.and_then(|x| serde_json::from_str::<serde_json::Value>(x).ok()) else { return MaterialSlop::default() };
    let Some(slop) = v.get("slop") else { return MaterialSlop::default() };
    let slot = match slop.get("slot").filter(|v| !v.is_null()) {
        None => None,
        Some(v) => match serde_json::from_value::<Slot>(v.clone()) {
            Ok(s) => Some(s),
            Err(_) => {
                warn_once(format!("handmade: {what}: slot {v} is not known; drawn as cloth"));
                Some(Slot::Cloth)
            }
        },
    };
    let hair = match (slot, slop.get("hair")) {
        (Some(Slot::Hair), Some(h)) => match hair_of(h) {
            Ok(p) => Some(p),
            Err(e) => {
                warn_once(format!("handmade: {what}: hair profile ignored ({e}); drawn as character hair"));
                None
            }
        },
        (_, Some(_)) => {
            warn_once(format!("handmade: {what}: a hair profile on a material whose slot is not \"hair\"; ignored"));
            None
        }
        _ => None,
    };
    let ink = match slop.get("ink") {
        None => None,
        Some(_) if slot == Some(Slot::Tint) => {
            warn_once(format!("handmade: {what}: ink on a tint, which is multiplied over the skin, is ignored; put the line on a carrier or on the skin"));
            None
        }
        Some(i) => match ink_of(i) {
            Ok(p) if slot.is_none() && p.map.is_none() => {
                warn_once(format!("handmade: {what}: ink on a material without a slot needs a map; ignored"));
                None
            }
            Ok(p) => Some(p),
            Err(e) => {
                warn_once(format!("handmade: {what}: ink ignored ({e}); drawn without ink"));
                None
            }
        },
    };
    if ink.is_some() && hair.as_ref().is_some_and(|h| h.inked) {
        warn_once(format!("handmade: {what}: both slop.ink and the hair profile's ink fields; slop.ink wins"));
    }
    MaterialSlop { slot, hair, ink }
}

/// An ink profile from its JSON, or what is wrong with it.
pub fn ink_of(v: &serde_json::Value) -> Result<InkProfile, String> {
    if !v.is_object() {
        return Err("ink is not an object".into());
    }
    let a = v["color"].as_array().ok_or("color is missing")?;
    let c: Vec<u8> = a.iter().filter_map(|x| x.as_u64().filter(|v| *v <= 255).map(|v| v as u8)).collect();
    if a.len() != 3 || c.len() != 3 {
        return Err("color is not three integers 0-255".into());
    }
    let num = |k: &str, d: f32| -> Result<f32, String> {
        match v.get(k) {
            None => Ok(d),
            Some(x) => x.as_f64().map(|x| x as f32).filter(|x| x.is_finite() && *x >= 0.0).ok_or(format!("{k} is not a number 0 or above")),
        }
    };
    let width = match v.get("width") {
        None => InkWidth::Px,
        Some(w) => serde_json::from_value::<InkWidth>(w.clone()).map_err(|_| format!("width {w} is not \"px\" or \"uv\""))?,
    };
    let taper = match v.get("taper") {
        None => false,
        Some(t) => t.as_bool().ok_or("taper is not true or false")?,
    };
    let range = match v.get("range") {
        None => INK_RANGE,
        Some(x) => x.as_f64().map(|x| x as f32).filter(|x| x.is_finite() && *x > 0.0).ok_or(format!("range {x} is not a number above 0"))?,
    };
    Ok(InkProfile {
        color: [c[0], c[1], c[2]],
        width,
        px: num("px", INK_PX)?,
        min_px: num("min_px", INK_MIN_PX)?,
        range,
        fade_px: num("fade_px", INK_FADE_PX)?,
        map: v["map"].as_str().map(String::from),
        taper,
    })
}

/// The ink map for a material of `file` with `slot`: the profile's own `map`, else
/// `<stem>.<slot>.ink.png` beside the file; each its KTX2 copy first.
pub fn ink_map(file: &str, slot: Option<Slot>, p: &InkProfile) -> Option<String> {
    let stem = file.trim_end_matches(".glb").trim_end_matches(".gltf");
    let own = slot.map(|s| format!("{stem}.{}.ink.png", s.name()));
    let root = crate::lookdev::asset_root();
    p.map.iter().cloned().chain(own).flat_map(|f| crate::lookdev::face_map_files(&f)).find(|f| std::path::Path::new(&root).join(f).exists())
}

impl InkProfile {
    /// Put the ink into a material's parameters: `colour_map` whether the map has colour
    /// channels (R as well as G), `m_uv` the mesh's texel density. Returns false (with a
    /// warning) when it can't be drawn.
    pub fn apply(&self, p: &mut ToonParams, colour_map: bool, m_uv: Option<f32>, what: &str) -> bool {
        let Some(m_uv) = m_uv else {
            warn_once(format!("handmade: {what}: ink on a mesh whose TEXCOORD_0 spans no area: no ink is drawn"));
            return false;
        };
        let mode = match self.width {
            InkWidth::Uv if !colour_map => {
                warn_once(format!("handmade: {what}: width \"uv\" with a greyscale ink map (no R): no ink is drawn"));
                return false;
            }
            // `LIVING_GAME_PERF=inkfw`: the half-width through the screen derivatives, as the
            // distance is (mode 4), for an A/B against the texel-density path.
            InkWidth::Uv if crate::perf::has("inkfw") => 4.0,
            InkWidth::Uv => 3.0,
            InkWidth::Px if self.taper && !colour_map => {
                warn_once(format!("handmade: {what}: taper with a greyscale ink map (no R): drawn at full width"));
                1.0
            }
            InkWidth::Px if self.taper => 2.0,
            InkWidth::Px => 1.0,
        };
        let w = if self.width == InkWidth::Uv { self.min_px } else { self.px };
        p.ink = linear(self.color).extend(w);
        p.ink_shape = Vec4::new(self.range, self.fade_px, mode, m_uv);
        true
    }
}

/// A hair profile from its JSON, or what is wrong with it.
pub fn hair_of(h: &serde_json::Value) -> Result<HairProfile, String> {
    let colour = |k: &str| -> Result<[u8; 3], String> {
        let a = h[k].as_array().ok_or(format!("{k} is missing"))?;
        let c: Vec<u8> = a.iter().filter_map(|x| x.as_u64().filter(|v| *v <= 255).map(|v| v as u8)).collect();
        if a.len() != 3 || c.len() != 3 {
            return Err(format!("{k} is not three integers 0-255"));
        }
        Ok([c[0], c[1], c[2]])
    };
    let num = |k: &str, d: f32| -> Result<f32, String> {
        match h.get(k) {
            None => Ok(d),
            Some(v) => v.as_f64().map(|x| x as f32).filter(|x| x.is_finite()).ok_or(format!("{k} is not a number")),
        }
    };
    let p = HairProfile {
        shade: colour("shade")?,
        mid: colour("mid")?,
        light: colour("light")?,
        highlight: colour("highlight")?,
        t1: num("t1", T1)?,
        t2: num("t2", T2)?,
        edge: num("edge", EDGE)?.max(0.0),
        feather: num("highlight_feather", FEATHER)?.clamp(0.0, 0.5),
        highlight_map: h["highlight_map"].as_str().map(String::from),
        inked: ["ink", "ink_px", "ink_range", "ink_fade_px"].iter().any(|k| h.get(*k).is_some()),
        ink: match h.get("ink") {
            None => None,
            Some(_) => match colour("ink") {
                Ok(c) => Some(c),
                Err(e) => {
                    warn_once(format!("handmade: hair profile: {e}; the ink is shade x 0.6"));
                    None
                }
            },
        },
        ink_px: num("ink_px", INK_PX)?.max(0.0),
        ink_range: num("ink_range", INK_RANGE)?,
        ink_fade_px: num("ink_fade_px", INK_FADE_PX)?.max(0.0),
    };
    if p.inked && p.ink_range <= 0.0 {
        return Err(format!("ink_range {} is not above 0", p.ink_range));
    }
    if p.t2 <= p.t1 {
        return Err(format!("t2 {} is not above t1 {}", p.t2, p.t1));
    }
    Ok(p)
}

/// The kind a slot shades as (`face_map`: whether a face shadow map was found).
pub fn kind_of(slot: Slot, profile: bool, face_map: bool) -> Kind {
    match slot {
        Slot::Hair if profile => Kind::HandHair,
        Slot::Hair => Kind::Hair,
        Slot::Skin => Kind::Skin,
        Slot::Face if face_map => Kind::Face,
        Slot::Face => Kind::Skin,
        Slot::Eyes => Kind::FacePart,
        Slot::Tint => Kind::Tint,
        Slot::Cloth => Kind::Plain,
    }
}

fn linear(c: [u8; 3]) -> Vec3 {
    let l = Color::srgb_u8(c[0], c[1], c[2]).to_linear();
    Vec3::new(l.red, l.green, l.blue)
}

impl HairProfile {
    /// Put the profile into a material's parameters (`mask`: the mask texture's path, if any).
    pub fn apply(&self, p: &mut ToonParams, mask: Option<&str>) {
        p.hand = [linear(self.shade).extend(0.0), linear(self.mid).extend(0.0), linear(self.light).extend(0.0), linear(self.highlight).extend(if mask.is_some() { 1.0 } else { 0.0 })];
        p.hand_bands = Vec4::new(self.t1, self.t2, self.edge, self.feather);
        let ink = self.inked && mask.is_some_and(has_green);
        if self.inked && !ink {
            warn_once(format!("handmade: ink fields set but no mask texture with a G channel ({mask:?}): no ink is drawn"));
        }
        let colour = self.ink.map(linear).unwrap_or(linear(self.shade) * 0.6);
        p.hand_ink = colour.extend(self.ink_px);
        p.hand_ink_range = Vec4::new(self.ink_range, self.ink_fade_px, if ink { 1.0 } else { 0.0 }, 0.0);
    }
}

/// The hair's texel density for the ink's fade: the median, over its triangles, of metres per UV
/// unit (the square root of a triangle's area over its UV area). None without UVs or area.
pub fn metres_per_uv(m: &Mesh) -> Option<f32> {
    let Some(bevy::mesh::VertexAttributeValues::Float32x3(pos)) = m.attribute(Mesh::ATTRIBUTE_POSITION) else { return None };
    let Some(bevy::mesh::VertexAttributeValues::Float32x2(uv)) = m.attribute(Mesh::ATTRIBUTE_UV_0) else { return None };
    let idx: Vec<usize> = match m.indices() {
        Some(i) => i.iter().collect(),
        None => (0..pos.len()).collect(),
    };
    let mut r: Vec<f32> = idx
        .chunks_exact(3)
        .filter_map(|t| {
            let (a, b, c) = (Vec3::from(pos[t[0]]), Vec3::from(pos[t[1]]), Vec3::from(pos[t[2]]));
            let (p, q, s) = (Vec2::from(uv[t[0]]), Vec2::from(uv[t[1]]), Vec2::from(uv[t[2]]));
            let area = (b - a).cross(c - a).length();
            let uv_area = (q - p).perp_dot(s - p).abs();
            (uv_area > 1e-12 && area > 0.0).then(|| (area / uv_area).sqrt())
        })
        .collect();
    if r.is_empty() {
        return None;
    }
    r.sort_by(f32::total_cmp);
    Some(r[r.len() / 2])
}

/// Whether a mask texture has a G channel (the ink field): a PNG's colour type says (RGB or
/// RGBA, not grey); a KTX2 copy is read through its PNG beside it, else taken to have one.
pub fn has_green(path: &str) -> bool {
    use std::io::Read;
    let png = if path.ends_with(".ktx2") { format!("{}.png", path.trim_end_matches(".ktx2")) } else { path.to_string() };
    let Ok(mut f) = std::fs::File::open(std::path::Path::new(&crate::lookdev::asset_root()).join(&png)) else { return path.ends_with(".ktx2") };
    let mut head = [0u8; 26];
    if f.read_exact(&mut head).is_err() || &head[1..4] != b"PNG" {
        return false;
    }
    matches!(head[25], 2 | 6)
}

/// The highlight mask texture for a profile hair of `file`, if there is one: the profile's own
/// `highlight_map`, else `<stem>.hair.png` beside the file; each the KTX2 copy first.
pub fn highlight_map(file: &str, p: &HairProfile) -> Option<String> {
    let own = format!("{}.hair.png", file.trim_end_matches(".glb").trim_end_matches(".gltf"));
    let root = crate::lookdev::asset_root();
    p.highlight_map.iter().cloned().chain(std::iter::once(own)).flat_map(|f| crate::lookdev::face_map_files(&f)).find(|f| std::path::Path::new(&root).join(f).exists())
}

/// A profile hair mesh's second UVs: x its `_GREY` (0 without), y 1 + its `_HIGHLIGHT` (0
/// without, so the shader takes no mask). Whatever second UVs the file gave it are replaced.
/// Returns whether it had a `_HIGHLIGHT`.
pub fn pack_highlight(m: &mut Mesh) -> bool {
    let n = m.count_vertices();
    let floats = |v: Option<bevy::mesh::VertexAttributeValues>| match v {
        Some(bevy::mesh::VertexAttributeValues::Float32(x)) if x.len() == n => Some(x),
        _ => None,
    };
    let high = floats(m.remove_attribute(ATTRIBUTE_HIGHLIGHT));
    let grey = floats(m.remove_attribute(crate::characters::compose::ATTRIBUTE_GREY));
    let uv: Vec<[f32; 2]> = (0..n).map(|i| [grey.as_ref().map_or(0.0, |g| g[i]), high.as_ref().map_or(0.0, |h| 1.0 + h[i].clamp(0.0, 1.0))]).collect();
    m.insert_attribute(Mesh::ATTRIBUTE_UV_1, uv);
    high.is_some()
}

/// A hand-made file's forward in a mesh's own frame, from the turn of each node between the
/// mesh and the character's root (`chain`, the root's child first). The root's frame faces −Z
/// once [`on_ready`] has turned a `"+Z"` file (`turned`), and the file's own way before.
pub fn local_forward(hm: &Handmade, turned: bool, chain: &[Quat]) -> Vec3 {
    let fwd = if hm.plus_z && !turned { Vec3::Z } else { Vec3::NEG_Z };
    let rel = chain.iter().fold(Quat::IDENTITY, |a, q| a * *q);
    (rel.inverse() * fwd).normalize_or(Vec3::NEG_Z)
}

/// A `"+Z"` file's root whose top nodes [`on_ready`] has turned half round.
#[derive(Component)]
pub struct Turned;

/// When a hand-made `"+Z"` file's scene spawns, turn it half round about the root's up, so it
/// faces −Z like every other character file and the roots' turns stay as they are. What turns is
/// each child of the root that is, or holds, one of the scene's top nodes (Bevy puts a glTF
/// scene's nodes under a scene root of its own), so pieces the client hangs on the root stay.
pub fn on_ready(
    ev: On<bevy::world_serialization::WorldInstanceReady>,
    mut commands: Commands,
    models: Query<(&crate::lookdev::Model, Option<&Children>)>,
    kids: Query<&Children>,
    names: Query<&Name>,
    mut transforms: Query<&mut Transform, Without<crate::lookdev::Model>>,
) {
    let Ok((model, children)) = models.get(ev.entity) else { return };
    let Some(hm) = of(&model.file).filter(|h| h.plus_z) else { return };
    let half = Quat::from_rotation_y(std::f32::consts::PI);
    let top = |e: Entity| names.get(e).is_ok_and(|nm| hm.tops.iter().any(|t| t == nm.as_str()));
    let mut n = 0;
    for c in children.into_iter().flatten() {
        if !(top(*c) || kids.get(*c).is_ok_and(|k| k.iter().any(top))) {
            continue;
        }
        if let Ok(mut tf) = transforms.get_mut(*c) {
            tf.rotation = half * tf.rotation;
            tf.translation = half * tf.translation;
            n += 1;
        }
    }
    commands.entity(ev.entity).insert(Turned);
    debug!("handmade: {}: {n} top nodes turned to face -Z", model.file);
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn file(slop: serde_json::Value) -> serde_json::Value {
        json!({"scenes": [{"nodes": [0], "extras": {"slop": slop}}], "nodes": [{"name": "Armature"}]})
    }

    #[test]
    fn a_scene_declares_a_handmade_character_and_its_forward() {
        let h = scene_of(&file(json!({"contract": 1, "character": "handmade", "forward": "+Z"})), "t").unwrap();
        assert!(h.plus_z);
        assert_eq!(h.tops, vec!["Armature".to_string()]);
        assert!(!scene_of(&file(json!({"contract": 1, "character": "handmade", "forward": "-Z"})), "t").unwrap().plus_z);
    }

    #[test]
    fn files_without_the_contract_are_not_handmade() {
        assert_eq!(scene_of(&json!({"scenes": [{"nodes": []}]}), "t"), None);
        assert_eq!(scene_of(&json!({"scenes": [{"extras": {"hair_fit": {}}}]}), "t"), None);
        assert_eq!(scene_of(&file(json!({"contract": 2, "character": "handmade", "forward": "+Z"})), "t"), None);
        assert_eq!(scene_of(&file(json!({"contract": 1, "character": "robot", "forward": "+Z"})), "t"), None);
    }

    fn profile() -> serde_json::Value {
        json!({"shade": [88, 42, 27], "mid": [152, 72, 43], "light": [184, 98, 60], "highlight": [214, 140, 96]})
    }

    #[test]
    fn a_hair_profile_takes_its_defaults_and_refuses_bad_values() {
        let p = hair_of(&profile()).unwrap();
        assert_eq!((p.t1, p.t2, p.edge, p.feather), (T1, T2, EDGE, FEATHER));
        let mut bad = profile();
        bad["t2"] = json!(-0.5);
        assert!(hair_of(&bad).is_err());
        let mut bad = profile();
        bad["light"] = json!([300, 0, 0]);
        assert!(hair_of(&bad).is_err());
        let mut bad = profile();
        bad.as_object_mut().unwrap().remove("highlight");
        assert!(hair_of(&bad).is_err());
    }

    #[test]
    fn ink_is_opt_in_and_checks_its_range() {
        let p = hair_of(&profile()).unwrap();
        assert!(!p.inked, "a v1 profile draws no ink");
        let mut inked = profile();
        inked["ink_range"] = json!(0.05);
        let p = hair_of(&inked).unwrap();
        assert!(p.inked);
        assert_eq!((p.ink, p.ink_px, p.ink_range, p.ink_fade_px), (None, INK_PX, 0.05, INK_FADE_PX));
        inked["ink"] = json!([20, 8, 4]);
        assert_eq!(hair_of(&inked).unwrap().ink, Some([20, 8, 4]));
        inked["ink_range"] = json!(0.0);
        assert!(hair_of(&inked).is_err());
    }

    #[test]
    fn ink_takes_its_defaults_and_its_width_mode() {
        let p = ink_of(&json!({"color": [34, 18, 16]})).unwrap();
        assert_eq!(p, InkProfile { color: [34, 18, 16], width: InkWidth::Px, px: INK_PX, min_px: INK_MIN_PX, range: INK_RANGE, fade_px: INK_FADE_PX, map: None, taper: false });
        let p = ink_of(&json!({"color": [0, 0, 0], "width": "uv", "min_px": 0.5, "range": 0.02, "fade_px": 0, "map": "view/x.ink.png", "taper": true})).unwrap();
        assert_eq!((p.width, p.min_px, p.range, p.fade_px, p.map.as_deref(), p.taper), (InkWidth::Uv, 0.5, 0.02, 0.0, Some("view/x.ink.png"), true));
    }

    #[test]
    fn ink_refuses_bad_values() {
        for bad in [
            json!([1, 2, 3]),
            json!({}),
            json!({"color": [300, 0, 0]}),
            json!({"color": [1, 2]}),
            json!({"color": [1, 2, 3], "range": 0}),
            json!({"color": [1, 2, 3], "range": -0.1}),
            json!({"color": [1, 2, 3], "px": -1}),
            json!({"color": [1, 2, 3], "fade_px": "wide"}),
            json!({"color": [1, 2, 3], "width": "mm"}),
            json!({"color": [1, 2, 3], "taper": 1}),
        ] {
            assert!(ink_of(&bad).is_err(), "{bad} was accepted");
        }
    }

    #[test]
    fn ink_is_opt_in_per_material_and_never_on_a_tint() {
        let ink = json!({"color": [10, 10, 10]});
        let eyes = material_of(Some(&json!({"slop": {"slot": "eyes", "ink": ink}}).to_string()), "t");
        assert_eq!(eyes.slot, Some(Slot::Eyes));
        assert_eq!(eyes.ink.unwrap().color, [10, 10, 10]);
        assert_eq!(material_of(Some(&json!({"slop": {"slot": "eyes"}}).to_string()), "t").ink, None);
        assert_eq!(material_of(Some(&json!({"slop": {"slot": "tint", "ink": ink}}).to_string()), "t").ink, None);
        // Without a slot the sidecar has no name: only an explicit map will do.
        assert_eq!(material_of(Some(&json!({"slop": {"ink": ink}}).to_string()), "t").ink, None);
        let mapped = json!({"color": [10, 10, 10], "map": "view/m.ink.png"});
        assert!(material_of(Some(&json!({"slop": {"ink": mapped}}).to_string()), "t").ink.is_some());
        // An invalid ink leaves the rest of the material's slop as it was.
        let hair = material_of(Some(&json!({"slop": {"slot": "hair", "hair": profile(), "ink": {"color": "black"}}}).to_string()), "t");
        assert!(hair.hair.is_some() && hair.ink.is_none());
    }

    #[test]
    fn slots_name_their_sidecars_by_serde() {
        for (slot, v) in [(Slot::Hair, json!("hair")), (Slot::Eyes, json!("eyes")), (Slot::Cloth, json!("cloth"))] {
            assert_eq!(serde_json::Value::String(slot.name()), v);
            assert_eq!(serde_json::from_value::<Slot>(v).unwrap(), slot);
        }
        // Every slot round-trips through its name.
        for slot in [Slot::Hair, Slot::Skin, Slot::Face, Slot::Eyes, Slot::Tint, Slot::Cloth] {
            assert_eq!(serde_json::from_value::<Slot>(serde_json::Value::String(slot.name())).unwrap(), slot);
        }
    }

    #[test]
    fn ink_goes_into_the_parameters_by_mode() {
        let mut p = ToonParams::default();
        let px = ink_of(&json!({"color": [255, 255, 255], "px": 2.0, "range": 0.01, "fade_px": 2.5})).unwrap();
        assert!(px.apply(&mut p, true, Some(0.05), "t"));
        assert_eq!(p.ink, Vec4::new(1.0, 1.0, 1.0, 2.0));
        assert_eq!(p.ink_shape, Vec4::new(0.01, 2.5, 1.0, 0.05));
        let taper = InkProfile { taper: true, ..px.clone() };
        assert!(taper.apply(&mut p, true, Some(0.05), "t"));
        assert_eq!(p.ink_shape.z, 2.0);
        // A greyscale map has no R: taper falls back to full width, "uv" draws nothing.
        assert!(taper.apply(&mut p, false, Some(0.05), "t"));
        assert_eq!(p.ink_shape.z, 1.0);
        let uv = InkProfile { width: InkWidth::Uv, min_px: 0.75, ..px.clone() };
        assert!(uv.apply(&mut p, true, Some(0.05), "t"));
        assert_eq!((p.ink.w, p.ink_shape.z), (0.75, 3.0));
        let mut q = ToonParams::default();
        assert!(!uv.apply(&mut q, false, Some(0.05), "t"));
        // A mesh whose UVs span no area takes no ink.
        assert!(!px.apply(&mut q, true, None, "t"));
        assert_eq!(q.ink_shape, Vec4::ZERO);
    }

    #[test]
    fn texel_density_is_metres_per_uv() {
        // A 2 m square mapped onto the unit UV square: 2 m per UV unit.
        let mut m = Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, Default::default());
        m.insert_attribute(Mesh::ATTRIBUTE_POSITION, vec![[0.0f32, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]]);
        m.insert_attribute(Mesh::ATTRIBUTE_UV_0, vec![[0.0f32, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]);
        m.insert_indices(bevy::mesh::Indices::U32(vec![0, 1, 2, 0, 2, 3]));
        assert!((metres_per_uv(&m).unwrap() - 2.0).abs() < 1e-5);
        let mut flat = m.clone();
        flat.insert_attribute(Mesh::ATTRIBUTE_UV_0, vec![[0.0f32, 1.0]; 4]);
        assert_eq!(metres_per_uv(&flat), None);
    }

    #[test]
    fn slots_choose_kinds() {
        let m = material_of(Some(&json!({"slop": {"slot": "hair", "hair": profile()}}).to_string()), "t");
        assert_eq!(m.slot, Some(Slot::Hair));
        assert_eq!(kind_of(Slot::Hair, m.hair.is_some(), false), Kind::HandHair);
        assert_eq!(kind_of(Slot::Hair, false, false), Kind::Hair);
        assert_eq!(kind_of(Slot::Face, false, false), Kind::Skin);
        assert_eq!(kind_of(Slot::Face, false, true), Kind::Face);
        assert_eq!(kind_of(Slot::Tint, false, false), Kind::Tint);
        assert_eq!(material_of(Some(&json!({"slop": {"slot": "wig"}}).to_string()), "t").slot, Some(Slot::Cloth));
        assert_eq!(material_of(Some(r#"{"face_map": "x.png"}"#), "t"), MaterialSlop::default());
        assert_eq!(material_of(None, "t"), MaterialSlop::default());
    }

    #[test]
    fn the_highlight_goes_into_the_second_uvs() {
        let mut m = Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, Default::default());
        m.insert_attribute(Mesh::ATTRIBUTE_POSITION, vec![[0.0f32; 3]; 3]);
        m.insert_attribute(ATTRIBUTE_HIGHLIGHT, vec![0.0f32, 0.75, 2.0]);
        assert!(pack_highlight(&mut m));
        let Some(bevy::mesh::VertexAttributeValues::Float32x2(uv)) = m.attribute(Mesh::ATTRIBUTE_UV_1) else { panic!() };
        assert_eq!(uv, &vec![[0.0, 1.0], [0.0, 1.75], [0.0, 2.0]]);
        let mut bare = Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, Default::default());
        bare.insert_attribute(Mesh::ATTRIBUTE_POSITION, vec![[0.0f32; 3]; 2]);
        bare.insert_attribute(Mesh::ATTRIBUTE_UV_1, vec![[0.5f32, 1.5]; 2]);
        assert!(!pack_highlight(&mut bare));
        let Some(bevy::mesh::VertexAttributeValues::Float32x2(uv)) = bare.attribute(Mesh::ATTRIBUTE_UV_1) else { panic!() };
        assert_eq!(uv, &vec![[0.0, 0.0]; 2]);
    }

    #[test]
    fn the_forward_follows_the_nodes_turns() {
        let plus = Handmade { plus_z: true, tops: vec![] };
        let minus = Handmade { plus_z: false, tops: vec![] };
        let half = Quat::from_rotation_y(std::f32::consts::PI);
        // Cora: her Armature is turned half round, her face points +Z.
        assert!(local_forward(&plus, false, &[half]).abs_diff_eq(Vec3::NEG_Z, 1e-5));
        // The same once on_ready has turned her top node again.
        assert!(local_forward(&plus, true, &[half * half]).abs_diff_eq(Vec3::NEG_Z, 1e-5));
        assert!(local_forward(&plus, false, &[]).abs_diff_eq(Vec3::Z, 1e-5));
        assert!(local_forward(&minus, false, &[]).abs_diff_eq(Vec3::NEG_Z, 1e-5));
    }
}
