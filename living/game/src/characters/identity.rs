//! A person's identity: values from -1 to 1 by name that move, scale and turn the identity bones
//! of a type's head (docs/CHARACTERS.md, "The client format" and "What the client needs for
//! types"). The rule is `living/tools/characters/compose.py`'s `transforms`, which the
//! generator's baked people match to 0.00 mm; this is a line-for-line port of it, and the test
//! below holds it to that file's numbers.
//!
//! - The rig (`types.json`'s `rig.bones`) gives each value its bone, what it does (`move`,
//!   `scale`, `turn`), its axis and its amounts at -1 (`least`) and 1 (`most`); at 0 it does
//!   nothing. A `move` is in thousandths of the head's height in the file (`file.head_height_m`),
//!   a `turn` in degrees.
//! - The rig's x, y, z are the file's X, -Z, Y; `o` is 0.55 x + 0.83 y. On a paired bone x points
//!   away from the midline on both sides and a turn has the same sense on both, so the right bone
//!   takes the left's values mirrored.
//! - A bone gets translation (its rest plus the move), rotation and scale; its children ride it.
//!
//! The rig is read from `characters/types.json` under the asset folder when the generator puts
//! one there, else from the copy compiled in (`living/tools/characters/types.json`).

use bevy::prelude::*;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::sync::OnceLock;

#[derive(Deserialize)]
struct Value {
    id: String,
    does: String,
    axis: String,
    least: f32,
    most: f32,
}

#[derive(Deserialize)]
struct Bone {
    name: String,
    mirrored: Option<String>,
    values: Vec<Value>,
}

#[derive(Deserialize)]
struct RigDef {
    bones: Vec<Bone>,
}

#[derive(Deserialize)]
struct FileDef {
    head_height_m: f32,
}

#[derive(Deserialize)]
struct TypesJson {
    file: FileDef,
    rig: RigDef,
}

/// The identity rig: its bones and values, and the head's height in a file (m).
pub struct Rig {
    bones: Vec<Bone>,
    pub head_m: f32,
}

/// The rig from `types.json` (read once).
pub fn rig() -> &'static Rig {
    static RIG: OnceLock<Rig> = OnceLock::new();
    RIG.get_or_init(|| {
        let path = std::path::Path::new(&crate::lookdev::asset_root()).join("characters/types.json");
        let text = std::fs::read_to_string(&path).unwrap_or_else(|_| include_str!("../../../tools/characters/types.json").to_string());
        match serde_json::from_str::<TypesJson>(&text) {
            Ok(t) => Rig { bones: t.rig.bones, head_m: t.file.head_height_m },
            Err(e) => {
                warn!("identity: types.json: {e}; identity values do nothing");
                Rig { bones: vec![], head_m: 0.0 }
            }
        }
    })
}

/// A bone's change from rest: a move (file units, added to its rest translation), a rotation
/// (in place of the rest's) and a scale.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Change {
    pub translate: Vec3,
    pub rotation: Option<Quat>,
    pub scale: Vec3,
}

impl Change {
    /// The bone's transform for a rest translation.
    pub fn transform(&self, rest: Vec3) -> Transform {
        Transform { translation: rest + self.translate, rotation: self.rotation.unwrap_or(Quat::IDENTITY), scale: self.scale }
    }
}

/// A value's amount for v in -1..1: a scale factor, a move in head heights, or degrees.
fn decode(v: &Value, x: f32) -> f32 {
    let rest = if v.does == "scale" { 1.0 } else { 0.0 };
    let x = x.clamp(-1.0, 1.0);
    let amount = if x >= 0.0 { rest + (v.most - rest) * x } else { rest + (v.least - rest) * -x };
    if v.does == "move" {
        amount / 1000.0
    } else {
        amount
    }
}

/// A rotation of `deg` degrees about a unit axis.
fn turn(axis: Vec3, deg: f32) -> Quat {
    Quat::from_axis_angle(axis, deg.to_radians())
}

/// Each identity bone's change for a set of values (by bone name, both sides of a pair).
pub fn transforms(rig: &Rig, values: &BTreeMap<String, f32>) -> Vec<(String, Change)> {
    let mut out = Vec::new();
    for bone in &rig.bones {
        let names = std::iter::once(bone.name.clone()).chain(bone.mirrored.clone());
        for name in names {
            let side: f32 = if name.ends_with("_L") || name.contains("_L_") {
                -1.0
            } else if name.ends_with("_R") || name.contains("_R_") {
                1.0
            } else {
                0.0
            };
            let s = if side != 0.0 { side } else { 1.0 };
            let mut c = Change { translate: Vec3::ZERO, rotation: None, scale: Vec3::ONE };
            for v in &bone.values {
                let amount = decode(v, values.get(&v.id).copied().unwrap_or(0.0));
                match v.does.as_str() {
                    "move" => {
                        let m = amount * rig.head_m;
                        let (x, y, z) = match v.axis.as_str() {
                            "x" => (1.0, 0.0, 0.0),
                            "y" => (0.0, 1.0, 0.0),
                            "z" => (0.0, 0.0, 1.0),
                            _ => (0.55, 0.83, 0.0),
                        };
                        // The rig's x is away from the midline (the file's X is the character's
                        // right, its left -X); its y is forward (-Z), its z up (Y).
                        c.translate += Vec3::new(m * x * s, m * z, -m * y);
                    }
                    "scale" => {
                        for k in v.axis.chars() {
                            match k {
                                'x' => c.scale.x *= amount,
                                'y' => c.scale.z *= amount,
                                'z' => c.scale.y *= amount,
                                _ => {}
                            }
                        }
                    }
                    _ if amount.abs() > 1e-9 => {
                        c.rotation = Some(match v.axis.as_str() {
                            // About the forward axis: the outer end up, on both sides.
                            "y" => turn(Vec3::Z, amount * s),
                            // About the upright axis: outward, on both sides.
                            "z" => turn(Vec3::Y, amount * s),
                            // About the axis across: the chin down.
                            _ => turn(Vec3::X, -amount),
                        });
                    }
                    _ => {}
                }
            }
            out.push((name, c));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `compose.py transforms` for three sets of values on the rig in the repository, written by
    /// `living/tools/characters/identity_cases.py`: bone → (move, rotation as x, y, z, w or null,
    /// scale), in file units.
    #[test]
    fn the_client_moves_the_bones_as_compose_py_does() {
        let cases: Vec<serde_json::Value> = serde_json::from_str(include_str!("identity_cases.json")).unwrap();
        let rig = rig();
        let mut checked = 0;
        for case in &cases {
            let values: BTreeMap<String, f32> = case["values"].as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.as_f64().unwrap() as f32)).collect();
            let ours: std::collections::HashMap<String, Change> = transforms(rig, &values).into_iter().collect();
            let theirs = case["bones"].as_object().unwrap();
            assert_eq!(ours.len(), theirs.len(), "the same bones");
            for (bone, t) in theirs {
                let c = ours.get(bone).unwrap_or_else(|| panic!("no {bone}"));
                let v3 = |a: &serde_json::Value| Vec3::new(a[0].as_f64().unwrap() as f32, a[1].as_f64().unwrap() as f32, a[2].as_f64().unwrap() as f32);
                assert!((c.translate - v3(&t[0])).length() < 1e-6, "{bone} move {:?} against {}", c.translate, t[0]);
                assert!((c.scale - v3(&t[2])).length() < 1e-6, "{bone} scale {:?} against {}", c.scale, t[2]);
                match (c.rotation, t[1].as_array()) {
                    (None, None) => {}
                    (Some(q), Some(r)) => {
                        let r = Quat::from_xyzw(r[0].as_f64().unwrap() as f32, r[1].as_f64().unwrap() as f32, r[2].as_f64().unwrap() as f32, r[3].as_f64().unwrap() as f32);
                        assert!(q.dot(r).abs() > 1.0 - 1e-6, "{bone} turn {q:?} against {r:?}");
                    }
                    (a, b) => panic!("{bone}: turn {a:?} against {b:?}"),
                }
                checked += 1;
            }
        }
        assert!(checked > 60, "{checked} bones checked");
    }
}
