//! Spike HUD in egui: status, camera tuning (F1), what my character perceives, proximity
//! chat, and names and speech over heads. The real game UI will not be egui.

use crate::camera::{Cam, PRESETS};
use crate::controls::{self, Input, Target};
use crate::net::{Net, Status};
use crate::world::Scene;
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
}

#[derive(Resource)]
pub struct Hud {
    pub tuning: bool,
    fps: f32,
}

impl Default for Hud {
    fn default() -> Self {
        Self { tuning: true, fps: 60.0 }
    }
}

/// How long a heard line stays over the speaker's head (ms of authority time).
const BUBBLE_MS: f64 = 7_000.0;

#[allow(clippy::too_many_arguments)]
pub fn draw(
    mut contexts: EguiContexts,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    mut cam: ResMut<Cam>,
    mut input: ResMut<Input>,
    mut hud: ResMut<Hud>,
    mut wants: ResMut<UiWants>,
    keys: Res<ButtonInput<KeyCode>>,
    target: Res<Target>,
    camq: Query<(&Camera, &Transform), With<Camera3d>>,
    time: Res<Time>,
) -> Result {
    let ctx = contexts.ctx_mut()?;
    hud.fps += (1.0 / time.delta_secs().max(1e-4) - hud.fps) * 0.05;
    if keys.just_pressed(KeyCode::F1) {
        hud.tuning = !hud.tuning;
    }
    let names: HashMap<u32, String> = net.conn.as_ref().map(|c| c.db.character().iter().map(|ch| (ch.id, ch.name)).collect()).unwrap_or_default();
    let mut experiences: Vec<Experience> = match (&net.conn, net.my_id) {
        (Some(c), Some(me)) => c.db.experience().iter().filter(|e| e.observer == me).collect(),
        _ => Vec::new(),
    };
    experiences.sort_by_key(|e| e.at_ms);

    // Status.
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
                if let Some(v) = c.db.vitals().id().find(&id) {
                    ui.label(format!("health {:.0}/{:.0} · hunger {:.0} · energy {:.0}", v.hp, v.max_hp, v.hunger, v.energy));
                }
            }
            ui.label(egui::RichText::new(format!("camera: {} · {:.0} fps", PRESETS[cam.preset].name, hud.fps)).small());
            if !net.detail.is_empty() {
                ui.colored_label(egui::Color32::LIGHT_RED, &net.detail);
            }
            if let Some(e) = net.errors.lock().unwrap().last() {
                ui.colored_label(egui::Color32::LIGHT_RED, e);
            }
            ui.label(egui::RichText::new("WASD move · Shift run · right click walk to · Enter talk · 1–4 camera · Q/E rotate (iso) · wheel zoom · F1 tuning").small().weak());
        });
    });

    // Camera tuning.
    if hud.tuning {
        egui::Window::new("Camera").anchor(egui::Align2::RIGHT_TOP, [-12.0, 10.0]).resizable(false).default_width(300.0).show(ctx, |ui| {
            for (i, p) in PRESETS.iter().enumerate() {
                if ui.selectable_label(cam.preset == i, format!("{} {}", i + 1, p.name)).on_hover_text(p.like).clicked() {
                    cam.set_preset(i);
                }
            }
            ui.label(egui::RichText::new(PRESETS[cam.preset].like).small().weak());
            ui.separator();
            let shown = cam.shown;
            let r = &mut cam.rig;
            let view = |ui: &mut egui::Ui, v: &mut crate::camera::View, label: &str| {
                ui.label(egui::RichText::new(label).small().strong());
                ui.add(egui::Slider::new(&mut v.pitch, 10.0..=89.0).text("pitch °"));
                ui.add(egui::Slider::new(&mut v.distance, 4.0..=80.0).text("distance"));
                ui.add(egui::Slider::new(&mut v.fov, 10.0..=70.0).text("fov °"));
            };
            ui.checkbox(&mut r.tilt, "zoom tilts the view (zoom-tilt)");
            if r.tilt {
                view(ui, &mut r.far, "zoomed out");
                view(ui, &mut r.near, "zoomed in");
            } else {
                view(ui, &mut r.far, "view");
            }
            ui.add(egui::Slider::new(&mut r.yaw, -180.0..=180.0).text("yaw °"));
            ui.checkbox(&mut r.ortho, "orthographic");
            ui.add(egui::Slider::new(&mut r.lead, 0.0..=10.0).text("cursor lean (tiles)"));
            ui.checkbox(&mut r.rotate_steps, "Q/E rotate 45°");
            ui.checkbox(&mut r.frame_talk, "frame conversations");
            ui.checkbox(&mut r.follow_heading, "yaw follows heading (opt-in)");
            ui.add(egui::Slider::new(&mut cam.zoom, 0.0..=1.0).text("zoom (wheel)"));
            ui.label(egui::RichText::new(format!("now: pitch {:.0}°, distance {:.1}, fov {:.0}°{}", shown.pitch, shown.distance, shown.fov, if cam.talk_partner.is_some() { " · framing a conversation" } else { "" })).small().weak());
        });
    }

    // What I perceive: my own experience rows, newest last.
    egui::Area::new(egui::Id::new("feed")).anchor(egui::Align2::LEFT_BOTTOM, [12.0, -46.0]).show(ctx, |ui| {
        ui.set_max_width(520.0);
        egui::Frame::popup(ui.style()).show(ui, |ui| {
            ui.label(egui::RichText::new("What you notice").small().strong());
            let mut lines: Vec<(u64, egui::RichText)> = input
                .said
                .iter()
                .map(|(t, text)| (*t, egui::RichText::new(format!("You: {text}")).color(egui::Color32::from_rgb(190, 220, 255))))
                .collect();
            for e in &experiences {
                let text = if e.kind == "speech" {
                    egui::RichText::new(&e.text).color(egui::Color32::from_rgb(250, 230, 160))
                } else {
                    egui::RichText::new(&e.text).small()
                };
                lines.push((e.at_ms, text));
            }
            lines.sort_by_key(|(t, _)| *t);
            for (_, text) in lines.into_iter().rev().take(9).rev() {
                ui.label(text);
            }
        });
    });

    // Chat input.
    let mut send = None;
    if input.chat_open {
        egui::Area::new(egui::Id::new("chat")).anchor(egui::Align2::LEFT_BOTTOM, [12.0, -10.0]).show(ctx, |ui| {
            let r = ui.add(egui::TextEdit::singleline(&mut input.chat).desired_width(520.0).hint_text("say something (only those within earshot hear you)"));
            r.request_focus();
            if ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                send = Some(std::mem::take(&mut input.chat));
                input.chat_open = false;
            }
            if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                input.chat.clear();
                input.chat_open = false;
            }
        });
    } else if keys.just_pressed(KeyCode::Enter) && !ctx.egui_wants_keyboard_input() {
        input.chat_open = true;
    }
    if let Some(text) = send {
        if controls::say(&net, &text) {
            input.said.push((scene.now_ms as u64, text.trim().to_string()));
        }
    }

    // Names and what I heard, over heads.
    if let Ok((camera, tf)) = camq.single() {
        // This frame's camera placement (the camera has no parent, so its global transform is
        // its transform; the propagated one still holds last frame's).
        let gtf = &GlobalTransform::from(*tf);
        let painter = ctx.layer_painter(egui::LayerId::background());
        let heard: HashMap<u32, String> = experiences
            .iter()
            .filter(|e| e.kind == "speech" && scene.now_ms - (e.at_ms as f64) < BUBBLE_MS)
            .map(|e| (e.subject, quoted(&e.text).to_string()))
            .chain(net.my_id.and_then(|me| input.said.last().filter(|(t, _)| scene.now_ms - (*t as f64) < BUBBLE_MS).map(|(_, l)| (me, l.clone()))))
            .collect();
        for (id, (p, _)) in &scene.shown {
            let at = scene.at3(p.x, p.y);
            if target.0.is_some_and(|me| me.distance(at) > 30.0) {
                continue;
            }
            let Ok(screen) = camera.world_to_viewport(gtf, at + Vec3::Y * 1.45) else { continue };
            let pos = egui::pos2(screen.x, screen.y);
            if let Some(name) = names.get(id) {
                painter.text(pos, egui::Align2::CENTER_BOTTOM, name, egui::FontId::proportional(12.0), egui::Color32::from_white_alpha(220));
            }
            if let Some(line) = heard.get(id) {
                let galley = painter.layout(line.clone(), egui::FontId::proportional(13.0), egui::Color32::BLACK, 260.0);
                let rect = egui::Rect::from_center_size(pos - egui::vec2(0.0, 16.0 + galley.size().y / 2.0), galley.size() + egui::vec2(12.0, 8.0));
                painter.rect_filled(rect, 6.0, egui::Color32::from_rgba_unmultiplied(250, 245, 225, 235));
                painter.galley(rect.min + egui::vec2(6.0, 4.0), galley, egui::Color32::BLACK);
            }
        }
    }

    wants.pointer = ctx.egui_wants_pointer_input() || ctx.is_pointer_over_egui();
    wants.keyboard = ctx.egui_wants_keyboard_input() || input.chat_open;
    Ok(())
}

/// The spoken words of a percept such as `Helper said: “Welcome!”` (the whole text otherwise).
fn quoted(text: &str) -> &str {
    match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => &text[a + '“'.len_utf8()..b],
        _ => text,
    }
}
