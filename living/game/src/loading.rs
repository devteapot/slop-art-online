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

pub struct LoadingPlugin;

impl Plugin for LoadingPlugin {
    fn build(&self, app: &mut App) {
        let count = Pipelines::default();
        app.insert_resource(count.clone())
            .insert_resource(Loading { fading: None, pipelines: (0, 0.0), done: false, prewarm: None })
            .add_systems(Startup, spawn)
            .add_systems(Update, prewarm)
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
            c.spawn((Text::new("Arriving…"), font, TextColor(Color::srgba(1.0, 1.0, 1.0, 0.85))));
        });
}

/// Spawn the prewarm characters once the island is there, packed round its arrival point (in the
/// camera's view and its shadow cascades).
fn prewarm(mut commands: Commands, assets: Res<AssetServer>, island: Option<Res<crate::island::Island>>, mut loading: ResMut<Loading>) {
    if loading.prewarm.is_some() || loading.done || !crate::characters::available() {
        return;
    }
    let Some(island) = island else { return };
    let recipes = crate::characters::Recipe::every_piece();
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
    info!("loading: {} prewarm characters wear every outfit piece", spawned.len());
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
    mut covers: Query<(Entity, &mut BackgroundColor, Option<&Children>, Has<UiTargetCamera>), With<Cover>>,
    mut texts: Query<&mut TextColor>,
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
        for (e, _, _, targeted) in &covers {
            if !targeted {
                commands.entity(e).insert(UiTargetCamera(cam));
            }
        }
    }
    let warmed = loading.prewarm.as_ref().is_none_or(|es| es.iter().all(|e| fitted.contains(*e)));
    let ready = island.as_ref().is_some_and(|i| i.settled()) && !me.is_empty() && warmed && now - loading.pipelines.1 > QUIET_S;
    if loading.fading.is_none() && (ready || now > MAX_S) {
        info!("loading: the first view is in after {now:.1} s ({n} pipelines)");
        loading.fading = Some(now);
        for e in loading.prewarm.take().unwrap_or_default() {
            commands.entity(e).despawn();
        }
        loading.prewarm = Some(Vec::new());
    }
    let Some(t0) = loading.fading else { return };
    let a = 1.0 - ((now - t0) / FADE_S).clamp(0.0, 1.0);
    for (e, mut bg, children, _) in &mut covers {
        if a <= 0.0 {
            commands.entity(e).despawn();
            continue;
        }
        bg.0 = bg.0.with_alpha(a);
        for c in children.into_iter().flatten() {
            if let Ok(mut t) = texts.get_mut(*c) {
                t.0 = t.0.with_alpha(0.85 * a);
            }
        }
    }
    if a <= 0.0 {
        loading.done = true;
    }
}
