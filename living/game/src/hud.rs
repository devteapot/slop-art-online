//! Developer panels in egui, behind F1 (hidden by default): connection status, camera tuning,
//! the look, the sight mock and look-dev controls. The player's UI is Bevy UI (`ui/`).

use crate::camera::Cam;
use crate::controls::Input;
use crate::net::{Net, Status};
use bevy::prelude::*;
use bevy_egui::{egui, EguiContexts};
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// Whether egui wants the pointer or keyboard this frame (then the game ignores them).
#[derive(Resource, Default)]
pub struct UiWants {
    pub pointer: bool,
    pub keyboard: bool,
    /// A list or a panel of the game UI is open (`verbs.rs`): the mouse picks from it, not the
    /// skill bar.
    pub menu: bool,
}

#[derive(Resource)]
pub struct Hud {
    pub tuning: bool,
    fps: f32,
}

impl Default for Hud {
    fn default() -> Self {
        Self { tuning: false, fps: 60.0 }
    }
}

#[allow(clippy::too_many_arguments)]
pub fn draw(
    mut contexts: EguiContexts,
    net: NonSend<Net>,
    mut cam: ResMut<Cam>,
    input: Res<Input>,
    mut hud: ResMut<Hud>,
    mut wants: ResMut<UiWants>,
    mut sight: ResMut<crate::sight::Sight>,
    mut my_size: ResMut<crate::bodies::MySize>,
    mut style: ResMut<crate::style::Style>,
    lookdev: Option<ResMut<crate::lookdev::Lookdev>>,
    envs: Option<ResMut<crate::envs::Envs>>,
    keys: Res<ButtonInput<KeyCode>>,
    time: Res<Time>,
) -> Result {
    let ctx = contexts.ctx_mut()?;
    hud.fps += (1.0 / time.delta_secs().max(1e-4) - hud.fps) * 0.05;
    if keys.just_pressed(KeyCode::F1) {
        hud.tuning = !hud.tuning;
    }
    let names: HashMap<u32, String> = net.conn.as_ref().map(|c| c.db.seen_characters().iter().map(|ch| (ch.id, ch.label)).chain(c.db.my_characters().iter().map(|ch| (ch.id, ch.name))).collect()).unwrap_or_default();

    // Status.
    if hud.tuning {
    egui::Area::new(egui::Id::new("status")).anchor(egui::Align2::LEFT_TOP, [12.0, 10.0]).show(ctx, |ui| {
        egui::Frame::popup(ui.style()).show(ui, |ui| {
            let state = match net.status {
                Status::Connecting => "connecting…",
                Status::Syncing => "syncing…",
                Status::Live => "live",
                Status::Offline => "offline",
            };
            ui.label(egui::RichText::new(format!("{} · {} · {state}", net.server, net.db)).small());
            match (net.my_id, net.my_body()) {
                (Some(id), Some(b)) => {
                    ui.label(format!("{} (#{id}) at {:.1}, {:.1}", names.get(&id).map_or(net.name.as_str(), |n| n.as_str()), b.x, b.y));
                }
                _ => {
                    ui.label(format!("joining as {}…", net.name));
                }
            }
            if let (Some(c), Some(id)) = (&net.conn, net.my_id) {
                if let Some(v) = c.db.my_vitals().id().find(&id) {
                    ui.label(format!("health {:.0}/{:.0} · hunger {:.0} · energy {:.0}", v.hp, v.max_hp, v.hunger, v.energy));
                }
            }
            ui.label(egui::RichText::new(format!("{:.0} fps", hud.fps)).small());
            if !net.detail.is_empty() {
                ui.colored_label(egui::Color32::LIGHT_RED, &net.detail);
            }
            if let Some(e) = net.errors.lock().unwrap().last() {
                ui.colored_label(egui::Color32::LIGHT_RED, e);
            }
            ui.label(egui::RichText::new("WASD move · Shift run · cursor: face and aim · R or middle-tap: turn to where you face · [ ] or middle-drag: rotate · Alt+mouse: glance · right click: walk to · Enter: talk · F1 panels").small().weak());
        });
    });

    }

    // Camera tuning.
    if hud.tuning {
        egui::Window::new("Camera").anchor(egui::Align2::RIGHT_TOP, [-12.0, 10.0]).resizable(false).default_width(300.0).show(ctx, |ui| {
            let shown = cam.shown;
            let r = &mut cam.rig;
            ui.label(egui::RichText::new("view").small().strong());
            ui.add(egui::Slider::new(&mut r.view.pitch, 15.0..=80.0).text("pitch °"));
            ui.add(egui::Slider::new(&mut r.view.distance, 5.0..=40.0).text("distance (m)"));
            ui.add(egui::Slider::new(&mut r.view.fov, 20.0..=70.0).text("fov °"));
            ui.label(egui::RichText::new("turning").small().strong());
            ui.checkbox(&mut r.steer, "turn by pointing at screen sides");
            if r.steer {
                ui.add(egui::Slider::new(&mut r.steer_zone, 0.1..=0.9).text("middle zone (no turn)"));
                ui.add(egui::Slider::new(&mut r.steer_rate, 0.0..=240.0).text("turn by pointing °/s"));
            }
            ui.add(egui::Slider::new(&mut r.rotate_rate, 20.0..=240.0).text("[ ] rotate °/s"));
            ui.add(egui::Slider::new(&mut r.lead, 0.0..=8.0).text("cursor lean (m)"));
            ui.checkbox(&mut r.frame, "frame talk, greetings and fights");
            ui.checkbox(&mut r.sight_bound, "never show further than sight");
            if ui.small_button("reset camera").clicked() {
                *r = crate::camera::Rig::default();
            }
            ui.separator();
            ui.add(egui::Slider::new(&mut my_size.0, 0.4..=3.0).text("my size (× adult)"));
            ui.label(egui::RichText::new(format!("now: pitch {:.0}°, distance {:.1} m, fov {:.0}°{}", shown.pitch, shown.distance * my_size.0.max(0.4), shown.fov, match cam.context { Some(crate::camera::Context::Fight) => " · framing a fight", Some(_) => " · framing a conversation", None => "" })).small().weak());
        });
    }

    // Look-dev scene controls.
    if let Some(mut look) = lookdev.filter(|_| hud.tuning) {
        egui::Window::new("Look dev").anchor(egui::Align2::CENTER_TOP, [0.0, 10.0]).resizable(false).show(ctx, |ui| {
            if let Some(mut envs) = envs {
                let names: Vec<String> = std::iter::once("Character line-up".to_string()).chain(envs.defs.iter().map(|d| d.name.clone())).collect();
                let mut want = envs.want;
                egui::ComboBox::from_label("environment (, .)").selected_text(names.get(want).cloned().unwrap_or_default()).show_ui(ui, |ui| {
                    for (i, n) in names.iter().enumerate() {
                        ui.selectable_value(&mut want, i, n);
                    }
                });
                if want != envs.want {
                    envs.want = want;
                }
                if let Some(d) = envs.want.checked_sub(1).and_then(|i| envs.defs.get(i)) {
                    ui.label(egui::RichText::new(&d.note).small().weak());
                }
                ui.label(egui::RichText::new("WASD walk · Shift run · assets: assets/envs/<id>/<kind>/*.glb").small().weak());
            }
            ui.add(egui::Slider::new(&mut look.hour, 6.0..=19.0).text("sun hour"));
            ui.horizontal(|ui| {
                for (a, label) in [(crate::lookdev::Act::Idle, "idle"), (crate::lookdev::Act::Walk, "walk"), (crate::lookdev::Act::Talk, "talk")] {
                    ui.selectable_value(&mut look.act, a, label);
                }
            });
            ui.label(egui::RichText::new(format!("{} model(s) from living/game/assets/lookdev", look.models.len())).small().weak());
        });
    }

    // The shared look (style profile).
    if hud.tuning {
        egui::Window::new("Look").anchor(egui::Align2::LEFT_TOP, [12.0, 120.0]).resizable(false).default_width(280.0).default_open(false).show(ctx, |ui| {
            let mut s = *style;
            ui.checkbox(&mut s.enabled, "toon look (off = plain, for comparison)");
            ui.add(egui::Slider::new(&mut s.exposure, 0.4..=1.4).text("brightness"));
            ui.add(egui::Slider::new(&mut s.threshold, -0.6..=0.6).text("light/shadow split (N·L)"));
            ui.add(egui::Slider::new(&mut s.softness, 0.0..=0.4).text("edge softness"));
            ui.add(egui::Slider::new(&mut s.shadow_depth, 0.0..=0.9).text("shadow depth"));
            ui.horizontal(|ui| {
                ui.label("shadow tint");
                ui.color_edit_button_rgb(&mut s.shadow_tint);
            });
            ui.add(egui::Slider::new(&mut s.core, 0.3..=1.0).text("far side (1 = no extra dark)"));
            ui.add(egui::Slider::new(&mut s.brush, 0.0..=1.0).text("brush breakup"));
            ui.add(egui::Slider::new(&mut s.brush_size, 0.2..=6.0).text("brush size (m)"));
            ui.add(egui::Slider::new(&mut s.rim, 0.0..=1.5).text("rim light"));
            ui.add(egui::Slider::new(&mut s.rim_width, 1.0..=8.0).text("rim tightness"));
            ui.checkbox(&mut s.outlines, "outlines");
            ui.add(egui::Slider::new(&mut s.outline_people, 0.0..=5.0).text("outline: people (px)"));
            ui.add(egui::Slider::new(&mut s.outline_things, 0.0..=5.0).text("outline: objects (px)"));
            ui.separator();
            ui.checkbox(&mut s.edges, "finishing pass: edge lines, screen rim, film gradient");
            ui.add(egui::Slider::new(&mut s.line_strength, 0.0..=1.0).text("edge lines"));
            ui.add(egui::Slider::new(&mut s.depth_threshold, 0.01..=0.3).text("depth edge threshold"));
            ui.add(egui::Slider::new(&mut s.normal_threshold, 0.05..=1.5).text("crease threshold"));
            ui.add(egui::Slider::new(&mut s.line_width, 0.5..=3.0).text("line width (px)"));
            ui.horizontal(|ui| {
                ui.label("line colour");
                ui.color_edit_button_rgb(&mut s.line_color);
            });
            ui.add(egui::Slider::new(&mut s.screen_rim, 0.0..=0.6).text("screen rim light"));
            ui.add(egui::Slider::new(&mut s.grade, 0.0..=0.6).text("film gradient"));
            ui.add(egui::Slider::new(&mut s.saturation, 0.6..=1.5).text("saturation"));
            ui.add(egui::Slider::new(&mut s.shadow_hue, 0.0..=1.0).text("shadow hue (target)"));
            ui.add(egui::Slider::new(&mut s.hue_shift, 0.0..=0.6).text("shadow hue shift"));
            ui.add(egui::Slider::new(&mut s.shadow_saturation, 0.5..=1.6).text("shadow saturation"));
            ui.horizontal(|ui| {
                ui.label("outline colour");
                ui.color_edit_button_rgb(&mut s.outline_color);
                if ui.small_button("reset look").clicked() {
                    s = crate::style::Style::default();
                }
            });
            if s != *style {
                *style = s;
            }
        });
    }

    // Perception mock.
    if hud.tuning {
        egui::Window::new("Sight (mock)").anchor(egui::Align2::RIGHT_BOTTOM, [-12.0, -10.0]).resizable(false).default_width(300.0).show(ctx, |ui| {
            ui.checkbox(&mut sight.enabled, "show only what I perceive");
            ui.add(egui::Slider::new(&mut sight.radius, 3.0..=40.0).text("sight (tiles)"));
            ui.horizontal(|ui| {
                for (label, r) in [("night 6", 6.0), ("torch 9", 9.0), ("day 11", 11.0), ("scout 20", 20.0)] {
                    if ui.small_button(label).clicked() {
                        sight.radius = r;
                    }
                }
            });
            ui.add(egui::Slider::new(&mut sight.cone, 30.0..=180.0).text("cone half-angle °"));
            ui.add(egui::Slider::new(&mut sight.close, 0.0..=6.0).text("all-round (tiles)"));
            ui.checkbox(&mut sight.remember, "remember seen ground");
            ui.label(egui::RichText::new("Client-only: the authority still sends everything (its laws: day 11, night 6, torch 9, hearing 9).").small().weak());
        });
    }

    wants.pointer = ctx.egui_wants_pointer_input() || ctx.is_pointer_over_egui();
    wants.keyboard = ctx.egui_wants_keyboard_input() || input.chat_open;
    Ok(())
}
