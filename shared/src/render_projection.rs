//! Reconstruct presentation from a fully applied SDK transaction. This module
//! contains no game rules or permission decisions. Call inside a row callback
//! or initial-subscription callback, or after an exclusively owned frame_tick,
//! before the connection processes another update.
use crate::module_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::Table;
use std::collections::BTreeMap;

pub const SUBSCRIPTIONS: [&str; 6] = [
    "SELECT * FROM sim_my_render_header",
    "SELECT * FROM sim_my_render_actors",
    "SELECT * FROM sim_my_render_bodies",
    "SELECT * FROM sim_my_render_sites",
    "SELECT * FROM sim_my_render_scene",
    "SELECT * FROM sim_my_render_events",
];

pub fn from_tables(db: &RemoteTables) -> Result<Option<Value>, String> {
    let Some(header) = db.sim_my_render_header().iter().next() else {
        return Ok(None);
    };
    let mut snapshot: Value = serde_json::from_str(&header.body).map_err(|e| e.to_string())?;
    if snapshot["incremental_observer"] == true {
        let Some(scene) = db
            .sim_my_render_scene()
            .iter()
            .find(|row| row.run == header.run)
        else {
            return Ok(None);
        };
        let scene: Value = serde_json::from_str(&scene.body).map_err(|e| e.to_string())?;
        snapshot = assemble(
            snapshot,
            scene,
            db.sim_my_render_actors()
                .iter()
                .filter(|row| row.run == header.run)
                .collect(),
            db.sim_my_render_bodies()
                .iter()
                .filter(|row| row.run == header.run)
                .collect(),
            db.sim_my_render_sites()
                .iter()
                .filter(|row| row.run == header.run)
                .collect(),
        )?;
    }
    let mut events: Vec<Value> = db
        .sim_my_render_events()
        .iter()
        .filter(|row| row.run == header.run)
        .map(|row| serde_json::from_str(&row.body).map_err(|e| e.to_string()))
        .collect::<Result<_, _>>()?;
    events.sort_by_key(|event| event["id"].as_u64().unwrap_or(0));
    snapshot["events"] = json!(events);
    Ok(Some(snapshot))
}

pub fn assemble(
    mut header: Value,
    mut scene: Value,
    actors: Vec<SimNativeActor>,
    supports: Vec<SimRenderBodySupport>,
    sites: Vec<SimNativeSite>,
) -> Result<Value, String> {
    let sources = scene
        .as_object_mut()
        .ok_or("invalid scene")?
        .remove("food_sources")
        .unwrap_or(json!([]));
    let selected = header
        .as_object_mut()
        .ok_or("invalid render header")?
        .remove("inspected_player")
        .unwrap_or(Value::Null);
    let can_participate = actors.iter().any(|row| row.actor == 3 && row.human);
    let players = players(&scene, selected, actors, supports)?;
    let sites = project_sites(&sources, sites);
    let body = header.as_object_mut().unwrap();
    body.remove("incremental_observer");
    body.remove("projection_revision");
    body.extend(scene.as_object().unwrap().clone());
    body.insert("players".into(), json!(players));
    body.insert("sites".into(), json!(sites));
    body.insert("can_participate".into(), json!(can_participate));
    Ok(header)
}

fn players(
    scene: &Value,
    selected: Value,
    mut actors: Vec<SimNativeActor>,
    supports: Vec<SimRenderBodySupport>,
) -> Result<Vec<Value>, String> {
    let supports: BTreeMap<_, _> = supports.into_iter().map(|row| (row.actor, row)).collect();
    actors.sort_by_key(|row| row.ordinal);
    let mut players = Vec::new();
    for row in actors {
        if selected["id"] == row.actor {
            players.push(selected.clone());
            continue;
        }
        let support = supports.get(&row.actor);
        let body = support
            .and_then(|s| s.body.as_ref())
            .map(|s| serde_json::from_str::<Value>(s).map_err(|e| e.to_string()))
            .transpose()?
            .unwrap_or(Value::Null);
        let mut player = json!({"id":row.actor,"name":row.name,"position":row.position,"health":row.health,
            "hunger":row.hunger,"energy":row.energy,"food":row.food,"controller":if row.human {"human"} else {"ai"},"body":body});
        let arena = scene["arenas"].as_array().and_then(|arenas| {
            arenas.iter().find(|arena| {
                if let Some(id) = support.and_then(|s| s.arena.as_ref()) {
                    arena["id"] == id.as_str()
                } else {
                    arena["actors"]
                        .as_array()
                        .is_some_and(|actors| actors.iter().any(|actor| actor == row.actor))
                }
            })
        });
        if let Some(arena) = arena {
            player["arena"] = arena["label"].clone();
            player["runtime"] = arena["controllers"][row.actor.to_string()].clone();
        }
        players.push(player);
    }
    Ok(players)
}
fn project_sites(sources: &Value, mut sites: Vec<SimNativeSite>) -> Vec<Value> {
    sites.sort_by_key(|row| row.ordinal);
    let sites:Vec<_>=sites.into_iter().map(|row| {
        let source=sources.as_array().and_then(|sources|sources.iter().find(|source|source["position"]==row.position));
        json!({"position":row.position,"food":row.food,"hazard":row.hazard,"shelter":row.shelter,"food_source":source})
    }).collect();
    sites
}

pub const ACTORS: u8 = 1;
pub const BODIES: u8 = 2;
pub const SITES: u8 = 4;
pub const SCENE: u8 = 8;
pub const EVENTS: u8 = 16;
pub const ALL: u8 = 31;

/// Retains unchanged presentation arrays across SDK updates. Refresh only after
/// frame_tick; dirty bits describe applied table changes, never authority rules.
#[derive(Default)]
pub struct Cache {
    run: Option<String>,
    scene: Value,
    selected: Value,
}
impl Cache {
    pub fn refresh(
        &mut self,
        db: &RemoteTables,
        snapshot: &mut Value,
        mut dirty: u8,
    ) -> Result<bool, String> {
        let Some(row) = db.sim_my_render_header().iter().next() else {
            *self = Self::default();
            *snapshot = Value::Null;
            return Ok(false);
        };
        let mut header: Value = serde_json::from_str(&row.body).map_err(|e| e.to_string())?;
        if header["incremental_observer"] != true {
            *snapshot = from_tables(db)?.unwrap_or(Value::Null);
            *self = Self::default();
            return Ok(!snapshot.is_null());
        }
        if self.run.as_ref() != Some(&row.run) || !snapshot.is_object() {
            dirty = ALL;
        }
        if dirty & SCENE != 0 {
            let Some(scene) = db.sim_my_render_scene().iter().find(|s| s.run == row.run) else {
                return Ok(false);
            };
            self.scene = serde_json::from_str(&scene.body).map_err(|e| e.to_string())?;
        }
        let selected = header
            .as_object_mut()
            .ok_or("invalid header")?
            .remove("inspected_player")
            .unwrap_or(Value::Null);
        if selected != self.selected {
            dirty |= ACTORS;
        }
        let projected_players = if dirty & (ACTORS | BODIES | SCENE) != 0 {
            Some(players(
                &self.scene,
                selected.clone(),
                db.sim_my_render_actors()
                    .iter()
                    .filter(|s| s.run == row.run)
                    .collect(),
                db.sim_my_render_bodies()
                    .iter()
                    .filter(|s| s.run == row.run)
                    .collect(),
            )?)
        } else {
            None
        };
        let projected_sites = if dirty & (SITES | SCENE) != 0 {
            Some(project_sites(
                &self.scene["food_sources"],
                db.sim_my_render_sites()
                    .iter()
                    .filter(|s| s.run == row.run)
                    .collect(),
            ))
        } else {
            None
        };
        let projected_events = if dirty & EVENTS != 0 {
            let mut events: Vec<Value> = db
                .sim_my_render_events()
                .iter()
                .filter(|s| s.run == row.run)
                .map(|s| serde_json::from_str(&s.body).map_err(|e| e.to_string()))
                .collect::<Result<_, _>>()?;
            events.sort_by_key(|e| e["id"].as_u64().unwrap_or(0));
            Some(events)
        } else {
            None
        };
        if dirty == ALL {
            *snapshot = json!({});
        }
        let output = snapshot.as_object_mut().ok_or("invalid cached snapshot")?;
        let header = header.as_object_mut().unwrap();
        header.remove("incremental_observer");
        header.remove("projection_revision");
        output.extend(std::mem::take(header));
        if dirty & SCENE != 0 {
            output.extend(
                self.scene
                    .as_object()
                    .ok_or("invalid scene")?
                    .iter()
                    .filter(|(key, _)| key.as_str() != "food_sources")
                    .map(|(key, value)| (key.clone(), value.clone())),
            );
        }
        if let Some(players) = projected_players {
            output.insert(
                "can_participate".into(),
                json!(players
                    .iter()
                    .any(|p| p["id"] == 3 && p["controller"] == "human")),
            );
            output.insert("players".into(), json!(players));
        }
        if let Some(sites) = projected_sites {
            output.insert("sites".into(), json!(sites));
        }
        if let Some(events) = projected_events {
            output.insert("events".into(), json!(events));
        }
        self.selected = selected;
        self.run = Some(row.run);
        Ok(true)
    }
}
