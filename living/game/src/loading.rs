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
//! whatever happens. Only the first load is covered: later arrivals stream in budgeted
//! (`island.rs`).
//!
//! **Prewarm.** Under the cover, a cluster of throwaway characters at the arrival point wears
//! every outfit piece of every base between them ([`crate::characters::Recipe::every_piece`]),
//! so the character variants a walk would meet later (a piece with its own vertex layout made a
//! 300 ms frame 2 km into `road:town>village3`) compile now. They go when the cover lifts. The tour, routes and the headless script's `ready` wait for it, so photographs
//! and route frame times never include it. The asset view has no cover.

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

pub struct LoadingPlugin;

impl Plugin for LoadingPlugin {
    fn build(&self, app: &mut App) {
        let count = Pipelines::default();
        app.insert_resource(count.clone())
            .insert_resource(Loading { fading: None, pipelines: (0, 0.0), done: false, prewarm: None })
            .add_systems(Startup, spawn)
            .add_systems(Update, prewarm)
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
    let (title, detail) = if net.ever_live || net.attempts == 0 {
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
}

/// Spawn the prewarm characters once the island is there, packed round its arrival point (in the
/// camera's view and its shadow cascades).
fn prewarm(mut commands: Commands, assets: Res<AssetServer>, island: Option<Res<crate::island::Island>>, mut loading: ResMut<Loading>) {
    if loading.prewarm.is_some() || loading.done || !crate::characters::available() {
        return;
    }
    let Some(island) = island else { return };
    let mut recipes = crate::characters::Recipe::every_piece();
    // And the fewest composed people that between them wear every type and style file in the
    // look book (`book::LookBook::covering`), so no composed material or mesh layout is first
    // drawn when someone comes into sight (`LIVING_GAME_PERF=nolooks` leaves them out, to
    // measure that hitch).
    let looks: Vec<crate::characters::Recipe> = match crate::characters::book::book() {
        Some(b) if crate::characters::compose::enabled() && !crate::perf::has("nolooks") => b.covering(&[]).iter().filter_map(|k| b.recipe(k).ok()).collect(),
        _ => Vec::new(),
    };
    let n_looks = looks.len();
    recipes.extend(looks);
    let at = island.start;
    let spawned = recipes
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let a = i as f32 * 2.4;
            let p = at + Vec2::new(a.cos(), a.sin()) * (1.2 + 0.25 * i as f32);
            crate::characters::spawn(&mut commands, &assets, r, Vec3::new(p.x, island.height(p.x, p.y), p.y), a)
        })
        .collect::<Vec<_>>();
    info!("loading: {} prewarm characters wear every outfit piece ({n_looks} composed, every type and style file in the look book)", spawned.len());
    loading.prewarm = Some(spawned);
}

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
    cams: Query<Entity, With<Camera3d>>,
    mut covers: Query<(Entity, &mut BackgroundColor, Has<UiTargetCamera>), With<Cover>>,
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
    // Headless captures render the camera into an image: the cover targets that camera.
    if let Some(cam) = cams.iter().next() {
        for (e, _, targeted) in &covers {
            if !targeted {
                commands.entity(e).insert(UiTargetCamera(cam));
            }
        }
    }
    let warmed = loading.prewarm.as_ref().is_none_or(|es| es.iter().all(|e| fitted.contains(*e)));
    let ready = island.as_ref().is_some_and(|i| i.settled()) && !me.is_empty() && warmed && now - loading.pipelines.1 > QUIET_S;
    // Connected play that never got through keeps its cover: it says why (`status`).
    let stranded = net.as_ref().is_some_and(|n| !crate::lookdev::enabled() && !n.ever_live);
    if loading.fading.is_none() && (ready || (now > MAX_S && !stranded)) {
        info!("loading: the first view is in after {now:.1} s ({n} pipelines)");
        loading.fading = Some(now);
        for e in loading.prewarm.take().unwrap_or_default() {
            commands.entity(e).despawn();
        }
        loading.prewarm = Some(Vec::new());
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
