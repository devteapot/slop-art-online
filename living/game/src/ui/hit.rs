//! The game UI's own pointer: what the cursor is over, clicks and drags, from the game's
//! cursor ([`crate::pointer::Pointer::pos`]) and the left button.
//!
//! One path for every way the cursor is driven: the system cursor when free, the drawn cursor
//! while the system one is captured (macOS reports a frozen position then, so Bevy's picking sees
//! nothing), and a headless script (`cursor:X,Y`, `mouse:left:down|up`). Widgets mark what takes
//! clicks with [`Hot`] and what is solid with [`Block`] (a window, the cluster, a button), and
//! read [`UiPointer`]: the hot node under the cursor, a click (pressed and let go on the same
//! node, without a drag), and a drag from a node (moved more than [`DRAG_PX`] while held), with
//! where it was let go.
//!
//! While the cursor is over a solid node, or a press or drag that began on one is under way,
//! the world does not take the pointer (`UiWants::game`): no strike, no view turn, no capture.
//! A trackpad's three-finger drag is a held press and a move, so it drags the same way.

use bevy::prelude::*;
use bevy::ui::{CalculatedClip, ComputedNode, ComputedStackIndex, UiGlobalTransform};

/// A press that moves this far (logical px) is a drag.
pub const DRAG_PX: f32 = 5.0;

/// Takes clicks (and drags, for nodes whose widget reads them).
#[derive(Component, Default)]
pub struct Hot;

/// Solid: the cursor over it is over the UI, not the world.
#[derive(Component, Default)]
pub struct Block;

/// A name for a node a script may click (`click:@NAME` in the live script; `verify-ui`), such
/// as `win:Pack:close`, `menu:Settings` or `pack:berries`.
#[derive(Component, Clone, Debug)]
pub struct Tag(pub String);

#[derive(Resource, Default, Debug)]
pub struct UiPointer {
    /// The cursor (logical px in the window).
    pub pos: Option<Vec2>,
    /// The topmost hot node under the cursor.
    pub over: Option<Entity>,
    /// The cursor is over a solid node.
    pub over_ui: bool,
    /// The hot node the left button went down on, and where (logical px).
    pub down: Option<(Entity, Vec2)>,
    /// A press that has become a drag (from `down`'s node).
    pub dragging: bool,
    /// Let go this frame: the node clicked (no drag), or a drag from a node let go here.
    pub clicked: Option<Entity>,
    pub dropped: Option<(Entity, Vec2)>,
    /// A press this frame that landed on no hot node (a click elsewhere closes lists).
    pub pressed_elsewhere: bool,
    /// The left button went down this frame over the world (outside any solid node).
    pub pressed_world: bool,
    /// Physical px per logical px of the UI's target, and the UI scale.
    pub scale: f32,
    pub ui_scale: f32,
    /// Tagged nodes shown now: their centre as fractions of the picture, and whether the
    /// cursor is over them.
    pub tags: std::collections::BTreeMap<String, Vec2>,
}

impl UiPointer {
    pub fn is_over(&self, e: Entity) -> bool {
        self.over == Some(e)
    }

    /// A position for a node placed at the cursor (UI `Val::Px` units).
    pub fn val(&self, logical: Vec2) -> Vec2 {
        logical / self.ui_scale.max(0.01)
    }

    /// How far the current press has moved (logical px).
    pub fn moved(&self) -> f32 {
        match (self.down, self.pos) {
            (Some((_, at)), Some(p)) => p.distance(at),
            _ => 0.0,
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn hit(
    pointer: Res<crate::pointer::Pointer>,
    mouse: Res<ButtonInput<MouseButton>>,
    cams: Query<&Camera, With<Camera3d>>,
    ui_scale: Res<UiScale>,
    nodes: Query<(Entity, &ComputedNode, &UiGlobalTransform, &InheritedVisibility, &ComputedStackIndex, Option<&CalculatedClip>, Has<Hot>), Or<(With<Hot>, With<Block>)>>,
    tagged: Query<(&Tag, &ComputedNode, &UiGlobalTransform, &InheritedVisibility, Option<&CalculatedClip>)>,
    mut ui: ResMut<UiPointer>,
    mut wants: ResMut<crate::hud::UiWants>,
) {
    ui.clicked = None;
    ui.dropped = None;
    ui.pressed_elsewhere = false;
    ui.pressed_world = false;
    ui.scale = cams.iter().find_map(|c| c.target_scaling_factor()).unwrap_or(1.0);
    let size = cams.iter().find_map(|c| c.physical_viewport_size()).map_or(Vec2::new(1600.0, 900.0), |s| s.as_vec2());
    ui.tags.clear();
    // Only scripts read tags (`click:@NAME`, `dump:`).
    let scripted = crate::live::scripted();
    for (t, n, tf, vis, clip) in tagged.iter().filter(|_| scripted) {
        let c = tf.affine().translation;
        if vis.get() && !n.is_empty() && clip.is_none_or(|k| k.contains_point(c)) {
            ui.tags.insert(t.0.clone(), c / size);
        }
    }
    ui.ui_scale = ui_scale.0;
    ui.pos = pointer.pos;
    let phys = ui.pos.map(|p| p * ui.scale);
    // The topmost marked node under the cursor (children draw over their parents, so a button
    // is above its window); it is what the cursor is over if it takes clicks.
    let mut top: Option<(u32, Entity, bool)> = None;
    if let Some(p) = phys {
        for (e, n, t, vis, stack, clip, hot) in &nodes {
            if !vis.get() || n.is_empty() || !n.contains_point(*t, p) || clip.is_some_and(|c| !c.contains_point(p)) {
                continue;
            }
            if top.is_none_or(|(s, _, _)| stack.0 >= s) {
                top = Some((stack.0, e, hot));
            }
        }
    }
    let over_ui = top.is_some();
    let over = top.filter(|t| t.2).map(|t| t.1);
    ui.over = over;
    ui.over_ui = over_ui;
    if mouse.just_pressed(MouseButton::Left) {
        match (over, ui.pos) {
            (Some(e), Some(at)) => ui.down = Some((e, at)),
            _ => {
                ui.down = None;
                ui.pressed_elsewhere = true;
                ui.pressed_world = !over_ui;
            }
        }
        ui.dragging = false;
    }
    if ui.down.is_some() && !ui.dragging && ui.moved() > DRAG_PX {
        ui.dragging = true;
    }
    if mouse.just_released(MouseButton::Left) || (ui.down.is_some() && !mouse.pressed(MouseButton::Left) && !mouse.just_pressed(MouseButton::Left)) {
        if let Some((from, _)) = ui.down.take() {
            if ui.dragging {
                ui.dropped = Some((from, ui.pos.unwrap_or_default()));
            } else if over == Some(from) {
                ui.clicked = Some(from);
            }
        }
        ui.dragging = false;
    }
    wants.game = over_ui || ui.down.is_some();
}
