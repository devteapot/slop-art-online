//! The first load, behind a plain cover (look-dev's island and connected play).
//!
//! Bevy 0.20 creates render pipelines synchronously on macOS (`bevy_render`'s
//! `create_pipeline_task` blocks there), inside the render set of the frame that first draws a
//! new material, mesh layout or pass. Each one composes its WESL, writes MSL and has Metal
//! compile it: tens of milliseconds warm, up to seconds while Metal's own shader cache is cold.
//! The first view of the island needs about a hundred, so the first load is a run of frames of
//! 0.1–3 s that can't be spread without patching Bevy. They happen here, under a cover in the
//! sky's colour with one line of text, instead of in front of you. The island's land generates on
//! a worker thread meanwhile (`envs::switch`, `live::land`).
//!
//! The cover lifts when the island and your character are in, every chunk in reach has its ground
//! and things and nothing waits to spawn, and no pipeline was created for [`QUIET_S`] s (the render
//! world counts them into [`Pipelines`]); it fades over [`FADE_S`]. It lifts after [`MAX_S`]
//! whatever happens, unless connected play never got through or the world is still being made
//! (staged genesis, `genesis.rs`): then it says "Preparing the world…", the step, the steps and
//! the step's label over a bar, and stays until you are in. Only the first load is covered: later arrivals stream in budgeted
//! (`island.rs`).
//!
//! **Prewarm.** Under the cover, a cluster of throwaway characters at the arrival point wears
//! every outfit piece of every base between them ([`crate::characters::Recipe::every_piece`]),
//! so the character variants a walk would meet later (a piece with its own vertex layout made a
//! 300 ms frame 2 km into `road:town>village3`) compile now. They go when the cover lifts. The tour, routes and the headless script's `ready` wait for it, so photographs
//! and route frame times never include it. The asset view has no cover.
//!
//! Beside them ([`scenery`], pipeline-prewarm) stand what play draws later in a pipeline the
//! first view lacks: a structure in the shared vertex-colour toon with a thing's outline (a
//! fallen fighter's remains: 144–270 ms when the first one came into sight on a cold Metal
//! cache), a fire's emissive flame, the combat effects' alpha and additive blends (670 ms at a
//! battle's first blow) and a heard sound's mark. The composed people include one wearing every
//! kind of mesh the look book holds that the perceived looks lack (`LookBook::covering_kinds`:
//! a braid's skinned cloth without UVs cost 323 ms when a battle's fighters arrived). The prewarm
//! people ([`Prewarm`]) draw their full and far models at once, outside the near-model cap, and
//! cast shadows and keep their outlines whatever their distance from the camera, which on a cold
//! load is still easing in over multi-second frames (pipeline-prewarm-2: the braid's shadow and
//! outline, 81 + 73 ms when a cold run's fighters arrived). Find what
//! is still missing with `LIVING_GAME_PERF=hitch,pipedefs`: every `pipelines:` line after
//! "the first view is in" is one, and its `pipedefs:` lines say which mesh and material.
//!
//! Only the settings of the session's start are prewarmed. A pipeline is keyed by its view too,
//! so changing the light (Classic, Look-dev) or the render scale in play compiles what the new
//! setting draws in the frames after the change, once per session: a stall the player asked
//! for, in the settings window, accepted rather than prewarming every setting's variants.

use bevy::prelude::*;
use bevy::render::render_resource::PipelineCache;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

/// The cover lifts once no pipeline was created for this long (s).
const QUIET_S: f32 = 0.75;
/// It lifts after this whatever else (s).
const MAX_S: f32 = 30.0;
/// Its fade (s).
const FADE_S: f32 = 0.35;

/// A prewarm person: drawn with its full and far models at once, outside the near-model cap
/// (`lookdev::far_models`), so both models' pipelines compile under the cover.
#[derive(Component)]
pub struct Prewarm;

/// A mesh of a prewarm person ([`mark_meshes`]): its outline is drawn at any distance from the
/// camera (`style::fog_outlines`).
#[derive(Component)]
pub struct PrewarmMesh;

/// Mark the prewarm people's meshes as they come in (their scenes spawn over later frames).
fn mark_meshes(mut commands: Commands, loading: Res<Loading>, children: Query<&Children>, meshes: Query<(), (With<Mesh3d>, Without<PrewarmMesh>)>) {
    for &e in loading.prewarm.iter().flatten() {
        for d in children.iter_descendants(e) {
            if meshes.contains(d) {
                commands.entity(d).insert(PrewarmMesh);
            }
        }
    }
}

/// Pipelines the render world has created (written there each frame).
#[derive(Resource, Clone, Default)]
pub struct Pipelines(pub Arc<AtomicUsize>);

#[derive(Resource)]
pub struct Loading {
    /// When the cover started fading (elapsed s), once everything is in.
    fading: Option<f32>,
    /// The pipeline count last seen, and since when it held.
    pipelines: (usize, f32),
    pub done: bool,
    /// The prewarm characters, once spawned.
    prewarm: Option<Vec<Entity>>,
    /// The prewarm scenery and effects, once spawned ([`scenery`]).
    scenery: Option<Vec<Entity>>,
    /// What the cover says now: its title, its detail line and its bar's share (shown while the
    /// world is being made), for the UI dump.
    pub cover: (String, String, Option<f32>),
}

impl Loading {
    /// Whether scripted shots and routes may go (the cover is gone, or there is none).
    pub fn clear(loading: Option<&Loading>) -> bool {
        loading.is_none_or(|l| l.done)
    }
}

#[derive(Component)]
struct Cover;

/// The cover's second line: why the world can't be reached, and when it is tried again.
#[derive(Component)]
struct CoverDetail;

/// The cover's bar (shown while the world is being made) and its fill.
#[derive(Component)]
struct CoverBar;
#[derive(Component)]
struct CoverFill;

/// The bar's width (UI px).
const BAR_W: f32 = 320.0;

pub struct LoadingPlugin;

impl Plugin for LoadingPlugin {
    fn build(&self, app: &mut App) {
        let count = Pipelines::default();
        app.insert_resource(count.clone())
            .insert_resource(Loading { fading: None, pipelines: (0, 0.0), done: false, prewarm: None, scenery: None, cover: ("Arriving…".into(), String::new(), None) })
            .add_systems(Startup, spawn)
            .add_systems(Update, (prewarm, scenery, mark_meshes))
            .add_systems(Update, status)
            .add_systems(Last, lift);
        if let Some(render) = app.get_sub_app_mut(bevy::render::RenderApp) {
            render.insert_resource(count).add_systems(bevy::render::Render, counted.after(bevy::render::RenderSystems::Render));
        }
    }
}

fn counted(cache: Res<PipelineCache>, count: Res<Pipelines>) {
    count.0.store(cache.pipelines().count(), Ordering::Relaxed);
}

fn spawn(mut commands: Commands, assets: Res<AssetServer>) {
    let font = TextFont { font: bevy::text::FontSource::Handle(assets.load("ui/fonts/Nunito-Variable.ttf")), font_size: bevy::text::FontSize::Px(22.0), ..default() };
    commands
        .spawn((
            Cover,
            Node { width: percent(100), height: percent(100), position_type: PositionType::Absolute, align_items: AlignItems::End, justify_content: JustifyContent::Center, padding: UiRect::bottom(percent(12)), ..default() },
            BackgroundColor(crate::camera::SKY),
            GlobalZIndex(i32::MAX),
        ))
        .with_children(|c| {
            c.spawn(Node { flex_direction: FlexDirection::Column, align_items: AlignItems::Center, row_gap: px(8), ..default() }).with_children(|col| {
                col.spawn((Text::new("Arriving…"), font.clone(), TextColor(Color::srgba(1.0, 1.0, 1.0, 0.95)), TextShadow::default()));
                col.spawn((CoverDetail, Text::new(""), TextFont { font_size: bevy::text::FontSize::Px(15.0), ..font }, TextColor(Color::srgba(1.0, 1.0, 1.0, 0.9)), TextShadow::default(), TextLayout::justify(Justify::Center)));
                // How far the world's making is: a plain track and its fill, in the cover's own
                // white (no theme loads before the first view).
                col.spawn((
                    CoverBar,
                    Node { display: Display::None, width: px(BAR_W), height: px(6), margin: UiRect::top(px(6)), border_radius: BorderRadius::all(px(3)), overflow: Overflow::clip(), ..default() },
                    BackgroundColor(Color::srgba(1.0, 1.0, 1.0, 0.22)),
                ))
                .with_children(|bar| {
                    bar.spawn((CoverFill, Node { width: px(0), height: percent(100), border_radius: BorderRadius::all(px(3)), ..default() }, BackgroundColor(Color::srgba(1.0, 1.0, 1.0, 0.85))));
                });
            });
        });
}

/// What the cover says while connected play has never got through: the server and why, and when
/// it is tried again (play-test 1: "Arriving…" stayed up forever with nothing said).
#[allow(clippy::too_many_arguments)]
fn status(
    net: Option<NonSend<crate::net::Net>>,
    time: Res<Time>,
    island: Option<Res<crate::island::Island>>,
    target: Res<crate::controls::Target>,
    covers: Query<Entity, With<Cover>>,
    children: Query<&Children>,
    mut texts: Query<(&mut Text, Has<CoverDetail>)>,
    mut bars: Query<&mut Node, (With<CoverBar>, Without<CoverFill>)>,
    mut fills: Query<&mut Node, (With<CoverFill>, Without<CoverBar>)>,
    mut loading: ResMut<Loading>,
) {
    let Some(net) = net.filter(|_| !crate::lookdev::enabled()) else { return };
    // Where the first load is, under "Arriving…": the world reached, the land drawn, then me.
    let stage = if net.status != crate::net::Status::Live {
        "Reaching the world"
    } else if island.is_none() {
        "Shaping the land"
    } else if target.0.is_none() || island.as_ref().is_some_and(|i| !i.settled()) {
        "Finding your way in"
    } else {
        ""
    };
    // The world is still being made (staged genesis): how far, over a bar.
    let preparing = net.genesis.text(time.elapsed_secs_f64());
    let share = preparing.as_ref().map(|_| net.genesis.bar);
    let (title, detail) = if let Some(t) = preparing {
        t
    } else if net.ever_live || net.attempts == 0 {
        ("Arriving…".to_string(), stage.to_string())
    } else if net.status == crate::net::Status::Offline {
        let why = if net.detail.contains("refused") || net.detail.contains("Connect") { "the server isn't answering".to_string() } else { net.detail.chars().take(90).collect() };
        let wait = (net.retry_at - time.elapsed_secs_f64()).max(0.0).ceil() as u32;
        ("Can't reach the world".to_string(), format!("{} · {}\n{why} · trying again {}", net.server, net.db, if wait > 0 { format!("in {wait} s (attempt {})", net.attempts) } else { "now".into() }))
    } else {
        ("Arriving…".to_string(), if net.attempts > 1 { format!("Connecting to {} · {} (attempt {})", net.server, net.db, net.attempts) } else { String::new() })
    };
    for cover in &covers {
        for c in children.iter_descendants(cover) {
            if let Ok((mut t, is_detail)) = texts.get_mut(c) {
                let want = if is_detail { &detail } else { &title };
                if &t.0 != want {
                    t.0 = want.clone();
                }
            }
        }
    }
    let display = if share.is_some() { Display::Flex } else { Display::None };
    for mut n in &mut bars {
        if n.display != display {
            n.display = display;
        }
    }
    let width = px(BAR_W * share.unwrap_or(0.0));
    for mut n in &mut fills {
        if n.width != width {
            n.width = width;
        }
    }
    if loading.cover.0 != title || loading.cover.1 != detail || loading.cover.2 != share {
        loading.cover = (title, detail, share);
    }
}

/// Spawn the prewarm characters once the island is there, packed round its arrival point (in the
/// camera's view and its shadow cascades).
///
/// With them, composed people for the looks the first view will show, so no composed material or
/// mesh layout is first drawn when someone comes into sight: the fewest lines that wear every type
/// and style file of the keys perceived when the cover is up (connected: `seen_characters`,
/// waiting up to [`LOOKS_WAIT_S`] for the rows; offline and in look-dev: the book's decor, which
/// the island's background people wear). Not the whole book: every file a prewarm loads stays
/// resident for the session (`characters::kept`), and the whole book's (64 people, 101 files)
/// held 140 MiB more GPU textures and peaked 700 MiB higher (look-1, Cullet).
/// `LIVING_GAME_PERF=nolooks` leaves them out, to measure the first-sight hitch.
///
/// The VRoid bases with every outfit piece (`Recipe::every_piece`) only when someone will fall
/// back to one (prewarm-worn-1): a world without looks (Brackenford, a world made before them),
/// offline and in look-dev, no book or composing off, or a person perceived with no look or a key
/// the book lacks. With every person in sight composed, none: their two files alone held about
/// 100 MiB of CPU meshes on a composed Cullet (`LIVING_GAME_PERF=meshfiles`). A VRoid person who
/// comes later loads the base then, a first-sight hitch. The player's own look is among the
/// perceived (`seen_characters` holds mine).
fn prewarm(mut commands: Commands, assets: Res<AssetServer>, island: Option<Res<crate::island::Island>>, mut loading: ResMut<Loading>, net: Option<NonSend<crate::net::Net>>, time: Res<Time>, mut since: Local<Option<f32>>) {
    if loading.prewarm.is_some() || loading.done || !crate::characters::available() {
        return;
    }
    let Some(island) = island else { return };
    let book = crate::characters::book::book().filter(|_| crate::characters::compose::enabled() && !crate::perf::has("nolooks"));
    let conn = net.as_ref().and_then(|n| n.conn.as_ref());
    let (keys, fallback): (Vec<String>, Fallback) = match conn {
        Some(conn) => {
            let people: Vec<String> = crate::net::characters(conn).into_iter().filter(|c| c.kind == "person").map(|c| c.look).collect();
            let mut keys: Vec<String> = people.iter().filter(|k| !k.is_empty()).cloned().collect();
            keys.sort();
            keys.dedup();
            // The rows come with the subscription; a world without looks has none to wait for.
            let started = *since.get_or_insert(time.elapsed_secs());
            let looks_world = !crate::characters::seen::world_generation(conn).is_empty();
            if book.is_some() && looks_world && keys.is_empty() && time.elapsed_secs() - started < LOOKS_WAIT_S {
                return;
            }
            let fallback = Fallback::of(book.is_some(), looks_world, &people, |k| book.is_some_and(|b| b.recipe(k).is_ok()));
            (keys, fallback)
        }
        None => (book.map(|b| b.decor.clone()).unwrap_or_default(), Fallback::Offline),
    };
    // `LIVING_GAME_PERF=prewarmall`: the bases always, as before (to measure).
    let fallback = if fallback == Fallback::None && crate::perf::has("prewarmall") { Fallback::Asked } else { fallback };
    let mut recipes = if fallback == Fallback::None { Vec::new() } else { crate::characters::Recipe::every_piece() };
    let n_bases = recipes.len();
    // With them, the lines that draw every other kind of mesh the book holds (`covering_kinds`).
    let (looks, n_kinds): (Vec<crate::characters::Recipe>, usize) = match book {
        Some(b) if !keys.is_empty() => {
            let worn = b.covering(&keys);
            let kinds = b.covering_kinds(&worn);
            (worn.iter().chain(&kinds).filter_map(|k| b.recipe(k).ok()).collect(), kinds.len())
        }
        _ => (Vec::new(), 0),
    };
    let n_looks = looks.len();
    // Connected, every person who comes into sight fades in (`live.rs`): their meshes carry the
    // dither (`fade.rs`), pipelines of their own. The island's background people don't. So the
    // composed lines are drawn both ways (the braid's cloth came in a fading fighter's dither
    // variant only, pipeline-prewarm).
    let faded: Vec<crate::characters::Recipe> = if conn.is_some() { looks.clone() } else { Vec::new() };
    let n_faded = faded.len();
    recipes.extend(looks);
    let plain = recipes.len();
    recipes.extend(faded);
    let at = island.start;
    let spawned = recipes
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let a = i as f32 * 2.4;
            let p = at + Vec2::new(a.cos(), a.sin()) * (1.2 + 0.25 * i as f32);
            let e = crate::characters::spawn(&mut commands, &assets, r, Vec3::new(p.x, island.height(p.x, p.y), p.y), a);
            commands.entity(e).insert(Prewarm);
            if i >= plain {
                commands.entity(e).insert(crate::fade::Fade::shown());
            }
            e
        })
        .collect::<Vec<_>>();
    info!("loading: {} prewarm characters ({n_looks} composed, every type and style file of the {} looks perceived and {n_kinds} for the book's other kinds of mesh, {n_faded} of them again fading; {n_bases} on VRoid bases wearing every outfit piece: {})", spawned.len(), keys.len(), fallback.why());
    loading.prewarm = Some(spawned);
}

/// Spawn the prewarm scenery and effects once the island is there, beside its arrival point:
/// what play draws later in a material, mesh layout or blend the first view lacks (see the
/// module's doc). `LIVING_GAME_PERF=noscenewarm` leaves them out, to measure the first-sight
/// hitch.
#[allow(clippy::too_many_arguments)]
fn scenery(
    mut commands: Commands,
    island: Option<Res<crate::island::Island>>,
    mut loading: ResMut<Loading>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut toons: ResMut<Assets<crate::style::Toon>>,
    mut palette: ResMut<crate::world::Palette>,
    style: Res<crate::style::Style>,
    fx: Option<Res<crate::vfx::Assets3>>,
    marks: Option<Res<crate::heardmark::HeardMarks>>,
    mut mats: ResMut<Assets<StandardMaterial>>,
) {
    if loading.scenery.is_some() || loading.done || crate::perf::has("noscenewarm") {
        return;
    }
    let Some(island) = island else { return };
    let p = island.start + Vec2::new(-1.6, 1.4);
    let at = Vec3::new(p.x, island.height(p.x, p.y), p.y);
    let mut spawned = crate::world::prewarm(&mut commands, &mut meshes, &mut toons, &mut palette, &style, at);
    // Combat effects and heard marks only where play has them (not look-dev's island).
    if let Some(fx) = fx {
        spawned.extend(crate::vfx::prewarm(&mut commands, &fx, at));
    }
    if let Some(marks) = marks {
        spawned.push(marks.prewarm(&mut commands, &mut mats, at + Vec3::X));
    }
    info!("loading: {} prewarm things and effects", spawned.len());
    loading.scenery = Some(spawned);
}

/// Why the prewarm wears the VRoid bases, or doesn't.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Fallback {
    /// Every person perceived is drawn from the book: no base.
    None,
    /// People perceived with no look or a key the book lacks.
    People(usize),
    /// A world without looks: everyone is drawn on a base.
    OldWorld,
    NoBook,
    Offline,
    /// `LIVING_GAME_PERF=prewarmall`.
    Asked,
}

impl Fallback {
    /// For a connected client: whether there is a book (and composing is on), whether the world
    /// has looks, the looks of the people perceived (empty for none) and whether the book draws a
    /// key.
    fn of(book: bool, looks_world: bool, people: &[String], draws: impl Fn(&str) -> bool) -> Self {
        if !book {
            return Fallback::NoBook;
        }
        if !looks_world {
            return Fallback::OldWorld;
        }
        match people.iter().filter(|k| k.is_empty() || !draws(k)).count() {
            0 => Fallback::None,
            n => Fallback::People(n),
        }
    }

    fn why(self) -> String {
        match self {
            Fallback::None => "none, every person in sight is composed".into(),
            Fallback::People(n) => format!("{n} people in sight without a look the book has"),
            Fallback::OldWorld => "a world without looks".into(),
            Fallback::NoBook => "no look book, or composing off".into(),
            Fallback::Offline => "offline or look-dev".into(),
            Fallback::Asked => "asked for (prewarmall)".into(),
        }
    }
}

/// How long the prewarm waits for perceived people's looks before it goes without them (s).
const LOOKS_WAIT_S: f32 = 5.0;

/// Lift the cover once the first view is in and pipelines have gone quiet.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn lift(
    mut commands: Commands,
    mut loading: ResMut<Loading>,
    count: Res<Pipelines>,
    time: Res<bevy::time::Time<bevy::time::Real>>,
    island: Option<Res<crate::island::Island>>,
    me: Query<(), (With<crate::lookdev::Fitted>, Or<(With<crate::envs::Player>, With<crate::gait::Feet>)>)>,
    fitted: Query<(), (With<crate::lookdev::Fitted>, With<crate::characters::outfit::Dressed>)>,
    cams: Query<(Entity, Has<bevy::ui::IsDefaultUiCamera>), Or<(With<bevy::ui::IsDefaultUiCamera>, With<Camera3d>)>>,
    mut covers: Query<(Entity, &mut BackgroundColor, Option<&UiTargetCamera>), With<Cover>>,
    mut texts: Query<&mut TextColor>,
    children: Query<&Children>,
    net: Option<NonSend<crate::net::Net>>,
) {
    if loading.done {
        return;
    }
    let now = time.elapsed_secs();
    let n = count.0.load(Ordering::Relaxed);
    if n != loading.pipelines.0 {
        loading.pipelines = (n, now);
    }
    // Headless captures and scaled 3D render into an image: the cover targets the active UI camera.
    let target_cam = cams.iter().find_map(|(e, def)| def.then_some(e)).or_else(|| cams.iter().next().map(|(e, _)| e));
    if let Some(cam) = target_cam {
        for (e, _, targeted) in &covers {
            if targeted.is_none_or(|t| t.0 != cam) {
                commands.entity(e).insert(UiTargetCamera(cam));
            }
        }
    }
    let warmed = loading.prewarm.as_ref().is_none_or(|es| es.iter().all(|e| fitted.contains(*e)));
    let ready = island.as_ref().is_some_and(|i| i.settled()) && !me.is_empty() && warmed && now - loading.pipelines.1 > QUIET_S;
    // Connected play that never got through keeps its cover: it says why (`status`).
    // So does a world still being made, until I am in it.
    let stranded = net.as_ref().is_some_and(|n| !crate::lookdev::enabled() && (!n.ever_live || n.genesis.preparing()));
    if loading.fading.is_none() && (ready || (now > MAX_S && !stranded)) {
        info!("loading: the first view is in after {now:.1} s ({n} pipelines)");
        crate::perf::LIFTED.store(true, Ordering::Relaxed);
        loading.fading = Some(now);
        for e in loading.prewarm.take().unwrap_or_default().into_iter().chain(loading.scenery.take().unwrap_or_default()) {
            commands.entity(e).despawn();
        }
        loading.prewarm = Some(Vec::new());
        loading.scenery = Some(Vec::new());
    }
    let Some(t0) = loading.fading else { return };
    let a = 1.0 - ((now - t0) / FADE_S).clamp(0.0, 1.0);
    for (e, mut bg, _) in &mut covers {
        if a <= 0.0 {
            commands.entity(e).despawn();
            continue;
        }
        bg.0 = bg.0.with_alpha(a);
        for c in children.iter_descendants(e) {
            if let Ok(mut t) = texts.get_mut(c) {
                t.0 = t.0.with_alpha(0.85 * a);
            }
        }
    }
    if a <= 0.0 {
        loading.done = true;
    }
}

#[cfg(test)]
mod tests {
    use super::Fallback;

    /// The VRoid bases are prewarmed only for people who will be drawn on one.
    #[test]
    fn the_bases_are_prewarmed_only_for_people_drawn_on_them() {
        let book = |k: &str| k.starts_with("lk_");
        let all = ["lk_a".to_string(), "lk_b".to_string()];
        assert_eq!(Fallback::of(true, true, &all, book), Fallback::None);
        // No look, or a key the book lacks: drawn on a base.
        assert_eq!(Fallback::of(true, true, &["lk_a".into(), String::new()], book), Fallback::People(1));
        assert_eq!(Fallback::of(true, true, &["lk_a".into(), "other".into(), String::new()], book), Fallback::People(2));
        // A world without looks (its rows may not be in yet), or no book: always.
        assert_eq!(Fallback::of(true, false, &all, book), Fallback::OldWorld);
        assert_eq!(Fallback::of(true, false, &[], book), Fallback::OldWorld);
        assert_eq!(Fallback::of(false, true, &all, book), Fallback::NoBook);
        // Nobody in sight on a looks world: nothing to fall back for.
        assert_eq!(Fallback::of(true, true, &[], book), Fallback::None);
    }
}
