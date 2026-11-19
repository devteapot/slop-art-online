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
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Deserialize)]
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
}

pub const T1: f32 = -0.20;
pub const T2: f32 = 0.40;
pub const EDGE: f32 = 0.02;
pub const FEATHER: f32 = 0.08;

/// What a material's extras declare.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct MaterialSlop {
    pub slot: Option<Slot>,
    pub hair: Option<HairProfile>,
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
    MaterialSlop { slot, hair }
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
    };
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
    /// Put the profile into a material's parameters (`mask_texture`: the mask is a texture).
    pub fn apply(&self, p: &mut ToonParams, mask_texture: bool) {
        p.hand = [linear(self.shade).extend(0.0), linear(self.mid).extend(0.0), linear(self.light).extend(0.0), linear(self.highlight).extend(if mask_texture { 1.0 } else { 0.0 })];
        p.hand_bands = Vec4::new(self.t1, self.t2, self.edge, self.feather);
    }
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
