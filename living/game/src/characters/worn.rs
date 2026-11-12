//! Composed people's files, counted by wearer (looks-mem-1): a type or style file stays loaded
//! while someone wears it, and for [`GRACE_S`] after the last wearer goes (they left sight, died,
//! or were redrawn under a new key), then its scene, meshes, materials and pictures are freed.
//!
//! Before this every file anyone had worn stayed for the session (`characters::kept`), so a
//! crowd that showed nearly every file held all of them (docs/LOOK.md §8: about 480 MiB resident
//! over VRoid bases for the whole book). Files that are not composed people's (VRoid bases,
//! beasts, the shared clip file) are still `kept`: there are only a few.
//!
//! - [`handle`]: the file's root glTF, loaded on first ask; the same handle while it is loaded
//!   (`compose::prepare` for style files, `characters::spawn` for the type file).
//! - [`Wears`]: the files a composed character wears; its hooks count the character in when it
//!   is added and out when it is removed or the entity despawned.
//! - [`free_unworn`]: once a second, frees the files no one has worn for [`GRACE_S`]: the
//!   registry's handle goes, and so do compose's plans and toons for them
//!   (`compose::Plans::forget`); Bevy then drops the assets as their last handles go.
//!
//! Someone walking out of sight and back within the grace keeps their files; a file freed is read
//! again by the next wearer. Only a file no one wears is freed, so no live instance is rebuilt by
//! a second read (crowd-1's fault, `characters::FileHandle`).

use bevy::ecs::lifecycle::HookContext;
use bevy::ecs::world::DeferredWorld;
use bevy::gltf::Gltf;
use bevy::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

/// How long a file no one wears stays loaded (s): someone stepping out of sight and back keeps
/// it. `LIVING_GAME_PERF=keepworn` keeps every file for the session, as before (to measure).
pub const GRACE_S: f32 = 20.0;

#[derive(Default)]
struct Entry {
    handle: Option<Handle<Gltf>>,
    wearers: u32,
    idle_since: Option<Instant>,
}

#[derive(Default)]
struct Registry {
    files: HashMap<String, Entry>,
    freed: u64,
    loads: u64,
}

fn registry() -> std::sync::MutexGuard<'static, Registry> {
    static R: OnceLock<Mutex<Registry>> = OnceLock::new();
    R.get_or_init(Default::default).lock().unwrap()
}

/// A composed person's file's root glTF: the one loaded, else a new load. Not a wearer by itself:
/// [`Wears`] counts.
pub fn handle(assets: &AssetServer, file: &str) -> Handle<Gltf> {
    let mut r = registry();
    let r = &mut *r;
    let e = r.files.entry(file.to_string()).or_insert_with(|| Entry { idle_since: Some(Instant::now()), ..default() });
    if e.handle.is_none() {
        r.loads += 1;
        e.handle = Some(assets.load(file.to_string()));
    }
    e.handle.clone().unwrap()
}

/// The files a composed character wears (its type's and its style files), counted while it is
/// on the entity.
#[derive(Component, Clone, Debug)]
#[component(on_add = on_add, on_remove = on_remove)]
pub struct Wears(pub Vec<String>);

fn on_add(world: DeferredWorld, ctx: HookContext) {
    let Some(w) = world.get::<Wears>(ctx.entity) else { return };
    let mut r = registry();
    for f in &w.0 {
        let e = r.files.entry(f.clone()).or_default();
        e.wearers += 1;
        e.idle_since = None;
    }
}

fn on_remove(world: DeferredWorld, ctx: HookContext) {
    let Some(w) = world.get::<Wears>(ctx.entity) else { return };
    let mut r = registry();
    for f in &w.0 {
        if let Some(e) = r.files.get_mut(f) {
            e.wearers = e.wearers.saturating_sub(1);
            if e.wearers == 0 {
                e.idle_since = Some(Instant::now());
            }
        }
    }
}

/// What the registry holds: files worn now, files loaded but worn by no one (in their grace),
/// files freed and loads made this session (the UI dump's `worn`, the `worn:` log line).
#[derive(Clone, Copy, Debug, Default, PartialEq, serde::Serialize)]
pub struct Stats {
    pub worn: usize,
    pub idle: usize,
    pub freed: u64,
    pub loads: u64,
}

pub fn stats() -> Stats {
    let r = registry();
    Stats {
        worn: r.files.values().filter(|e| e.handle.is_some() && e.wearers > 0).count(),
        idle: r.files.values().filter(|e| e.handle.is_some() && e.wearers == 0).count(),
        freed: r.freed,
        loads: r.loads,
    }
}

/// The loaded files no one has worn for `grace` s by `now`, their handles taken (`free_unworn`).
fn take_unworn(r: &mut Registry, now: Instant, grace: f32) -> HashSet<String> {
    let mut gone = HashSet::new();
    for (f, e) in r.files.iter_mut() {
        if e.handle.is_some() && e.wearers == 0 && e.idle_since.is_some_and(|t| now.duration_since(t).as_secs_f32() >= grace) {
            e.handle = None;
            gone.insert(f.clone());
        }
    }
    r.files.retain(|_, e| e.handle.is_some() || e.wearers > 0);
    r.freed += gone.len() as u64;
    gone
}

/// Free the files no one has worn for [`GRACE_S`], once a second.
pub fn free_unworn(time: Res<Time>, mut since: Local<f32>, mut plans: ResMut<super::compose::Plans>) {
    *since += time.delta_secs();
    if *since < 1.0 || crate::perf::has("keepworn") {
        return;
    }
    *since = 0.0;
    let gone = take_unworn(&mut registry(), Instant::now(), GRACE_S);
    if gone.is_empty() {
        return;
    }
    plans.forget(&gone);
    let s = stats();
    let mut names: Vec<&str> = gone.iter().map(|f| f.trim_start_matches("lookdev/")).collect();
    names.sort();
    info!("worn: freed {} file(s) no one has worn for {GRACE_S:.0} s ({}); {} worn, {} idle, {} freed this session", gone.len(), names.join(", "), s.worn, s.idle, s.freed);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn a_file_is_freed_only_after_its_last_wearer_and_the_grace() {
        let mut r = Registry::default();
        let t0 = Instant::now();
        let worn = |r: &mut Registry, f: &str, n: u32, idle: Option<Instant>| {
            r.files.insert(f.into(), Entry { handle: Some(Handle::default()), wearers: n, idle_since: idle });
        };
        worn(&mut r, "a", 1, None);
        worn(&mut r, "b", 0, Some(t0));
        worn(&mut r, "c", 0, Some(t0 + Duration::from_secs(15)));
        let gone = take_unworn(&mut r, t0 + Duration::from_secs(21), GRACE_S);
        assert_eq!(gone, HashSet::from(["b".to_string()]));
        assert!(r.files.contains_key("a") && r.files.contains_key("c") && !r.files.contains_key("b"));
        assert_eq!(r.freed, 1);
        // Worn again before its grace ran out: kept.
        r.files.get_mut("c").unwrap().wearers = 1;
        r.files.get_mut("c").unwrap().idle_since = None;
        assert!(take_unworn(&mut r, t0 + Duration::from_secs(60), GRACE_S).is_empty());
    }
}
