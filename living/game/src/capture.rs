//! Photographs for scripted runs (asset view batches, environment tours). Batch runs are headless
//! by default: no window opens; the camera renders into an image of `LIVING_GAME_SIZE` (default
//! 1600x900) and photographs are read back from it. `LIVING_GAME_WINDOW=1` shows the window
//! instead.

use bevy::camera::RenderTarget;
use bevy::prelude::*;
use bevy::render::render_resource::{TextureFormat, TextureUsages};
use bevy::render::view::screenshot::{save_to_disk, Screenshot};
use std::path::PathBuf;

/// Whether this run is a script with no one watching (it writes photographs and quits).
pub fn scripted() -> bool {
    let set = |k: &str| std::env::var(k).is_ok_and(|v| !v.is_empty());
    (crate::view::enabled() && set("LIVING_GAME_VIEW_OUT")) || (crate::lookdev::enabled() && set("LIVING_GAME_TOUR"))
}

pub fn headless() -> bool {
    scripted() && !std::env::var("LIVING_GAME_WINDOW").is_ok_and(|v| !v.is_empty() && v != "0")
}

pub fn size() -> UVec2 {
    std::env::var("LIVING_GAME_SIZE")
        .ok()
        .and_then(|s| {
            let (w, h) = s.split_once('x')?;
            Some(UVec2::new(w.parse().ok()?, h.parse().ok()?))
        })
        .unwrap_or(UVec2::new(1600, 900))
}

/// The image a headless camera renders into.
#[derive(Resource)]
pub struct Target(pub Handle<Image>);

pub fn setup(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let s = size();
    let mut image = Image::new_target_texture(s.x, s.y, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC;
    commands.insert_resource(Target(images.add(image)));
}

/// Point new cameras at the headless image.
pub fn attach(mut commands: Commands, target: Option<Res<Target>>, cams: Query<Entity, Added<Camera3d>>) {
    let Some(target) = target else { return };
    for e in &cams {
        commands.entity(e).insert(RenderTarget::Image(target.0.clone().into()));
    }
}

/// Photograph what the camera sees into `path`.
pub fn shot(commands: &mut Commands, target: Option<&Target>, path: PathBuf) {
    let s = match target {
        Some(t) => Screenshot::image(t.0.clone()),
        None => Screenshot::primary_window(),
    };
    commands.spawn(s).observe(save_to_disk(path));
}
