//! The map: terrain, resources, structures, creatures, speech and day/night, drawn with
//! the egui painter in the central area (pan: drag/WASD, zoom: wheel, click: select).

use crate::state::{need, person_color, Snap, View};
use bevy_egui::egui::{self, Align2, Color32, FontId, Pos2, Rect, Stroke, StrokeKind, Vec2};
use living_rules::map::{MAP_H, MAP_W};

const SPEECH_MS: u64 = 6000;

struct Xf {
    rect: Rect,
    center: Pos2,
    zoom: f32,
}

impl Xf {
    fn s(&self, p: Pos2) -> Pos2 {
        self.rect.center() + (p - self.center) * self.zoom
    }
    fn w(&self, s: Pos2) -> Pos2 {
        self.center + (s - self.rect.center()) / self.zoom
    }
    /// Tile length → points, never smaller than `min`.
    fn r(&self, tiles: f32, min: f32) -> f32 {
        (tiles * self.zoom).max(min)
    }
}

fn a(c: Color32, alpha: f32) -> Color32 {
    let [r, g, b, _] = c.to_array();
    Color32::from_rgba_unmultiplied(r, g, b, (alpha.clamp(0.0, 1.0) * 255.0) as u8)
}

/// 0 by day, 1 at night, with dusk/dawn ramps.
pub fn darkness(h: f32) -> f32 {
    if (7.0..18.0).contains(&h) {
        0.0
    } else if (18.0..21.0).contains(&h) {
        (h - 18.0) / 3.0
    } else if (5.0..7.0).contains(&h) {
        1.0 - (h - 5.0) / 2.0
    } else {
        1.0
    }
}

pub fn central(ctx: &egui::Context, view: &mut View, snap: &Snap, t: f32) {
    egui::CentralPanel::default().frame(egui::Frame::NONE.fill(Color32::from_rgb(16, 22, 28))).show(ctx, |ui| {
        let rect = ui.max_rect();
        let resp = ui.allocate_rect(rect, egui::Sense::click_and_drag());
        // Fit the whole valley once the terrain has arrived (and on request).
        let fit = ui.input(|i| i.key_pressed(egui::Key::Home)) && !ui.ctx().wants_keyboard_input();
        if (!view.fitted && view.terrain.is_some() && rect.width() > 50.0) || fit {
            view.zoom = (rect.width().min(rect.height()) / MAP_W.max(MAP_H) as f32 * 0.96).max(2.0);
            view.center = egui::pos2(MAP_W as f32 / 2.0, MAP_H as f32 / 2.0);
            view.follow = false;
            view.fitted = true;
        }
        input(ui, &resp, view, rect);
        let xf = Xf { rect, center: view.center, zoom: view.zoom };
        let painter = ui.painter_at(rect);

        // Terrain.
        if let Some(tex) = &view.terrain {
            let r = Rect::from_min_max(xf.s(Pos2::ZERO), xf.s(egui::pos2(MAP_W as f32, MAP_H as f32)));
            painter.image(tex.id(), r, Rect::from_min_max(Pos2::ZERO, egui::pos2(1.0, 1.0)), Color32::WHITE);
            painter.rect_stroke(r, 0.0, Stroke::new(1.0, Color32::from_black_alpha(160)), StrokeKind::Outside);
        } else {
            painter.text(rect.center(), Align2::CENTER_CENTER, "waiting for the world…", FontId::proportional(18.0), Color32::GRAY);
        }

        resources(&painter, &xf, snap);
        structures(&painter, &xf, snap, t);
        selected_overlays(&painter, &xf, view, snap);
        creatures(&painter, &xf, view, snap);

        // Night falls over everything except fire light and labels.
        let dark = darkness(snap.hour());
        if dark > 0.0 {
            painter.rect_filled(rect, 0.0, Color32::from_rgba_unmultiplied(6, 10, 38, (dark * 175.0) as u8));
        }
        let dusk = (1.0 - ((snap.hour() - 18.5).abs() / 1.5)).max(0.0) + (1.0 - ((snap.hour() - 6.0).abs() / 1.0)).max(0.0);
        if dusk > 0.0 {
            painter.rect_filled(rect, 0.0, Color32::from_rgba_unmultiplied(255, 120, 40, (dusk * 22.0) as u8));
        }
        fire_glow(&painter, &xf, snap, t, dark);
        labels(&painter, &xf, view, snap);
        speech(&painter, &xf, view, snap);

        // Selection and hover.
        let hovered = resp.hover_pos().and_then(|p| pick(&xf, view, snap, p));
        if let (Some(id), Some(p)) = (hovered, resp.hover_pos()) {
            let mut s = snap.name(id);
            if let Some(act) = snap.activity.get(&id) {
                s.push_str(&format!(" — {}", act.label));
            }
            let g = painter.layout_no_wrap(s, FontId::proportional(13.0), Color32::WHITE);
            let r = Rect::from_min_size(p + egui::vec2(14.0, 10.0), g.size()).expand(4.0);
            painter.rect_filled(r, 4.0, Color32::from_black_alpha(200));
            painter.galley(r.min + egui::vec2(4.0, 4.0), g, Color32::WHITE);
            ctx.set_cursor_icon(egui::CursorIcon::PointingHand);
        }
        if resp.clicked() || resp.double_clicked() {
            let at = resp.interact_pointer_pos().or(resp.hover_pos());
            if let Some(id) = at.and_then(|p| pick(&xf, view, snap, p)) {
                view.selected = Some(id);
                if resp.double_clicked() {
                    view.follow = true;
                }
            }
        }

        // Legend / hint.
        let fit_btn = Rect::from_min_size(rect.right_top() + egui::vec2(-74.0, 8.0), egui::vec2(66.0, 22.0));
        if ui.put(fit_btn, egui::Button::new("Fit map")).clicked() {
            view.fitted = false;
        }
        let hint = "drag or WASD to pan · wheel to zoom · click to inspect · double-click to follow · Home to fit";
        painter.text(rect.left_bottom() + egui::vec2(10.0, -8.0), Align2::LEFT_BOTTOM, hint, FontId::proportional(11.5), Color32::from_white_alpha(150));
    });
}

fn input(ui: &egui::Ui, resp: &egui::Response, view: &mut View, rect: Rect) {
    if resp.dragged() {
        let d = resp.drag_delta();
        if d != Vec2::ZERO {
            view.center -= d / view.zoom;
            view.follow = false;
        }
    }
    if resp.hovered() {
        let (scroll, zoom_delta, pointer) = ui.input(|i| (i.smooth_scroll_delta.y, i.zoom_delta(), i.pointer.hover_pos()));
        let factor = ((scroll * 0.0015).clamp(-0.25, 0.25)).exp() * zoom_delta;
        if (factor - 1.0).abs() > 1e-4 {
            let old = view.zoom;
            view.zoom = (view.zoom * factor).clamp(2.0, 90.0);
            // Keep the world point under the cursor fixed (unless following).
            if let (Some(p), false) = (pointer, view.follow) {
                let xf = Xf { rect, center: view.center, zoom: old };
                let w = xf.w(p);
                view.center = w - (p - rect.center()) / view.zoom;
            }
        }
    }
    if !ui.ctx().wants_keyboard_input() {
        let dt = ui.input(|i| i.stable_dt).min(0.1);
        let mut d = Vec2::ZERO;
        ui.input(|i| {
            if i.key_down(egui::Key::W) || i.key_down(egui::Key::ArrowUp) {
                d.y -= 1.0;
            }
            if i.key_down(egui::Key::S) || i.key_down(egui::Key::ArrowDown) {
                d.y += 1.0;
            }
            if i.key_down(egui::Key::A) || i.key_down(egui::Key::ArrowLeft) {
                d.x -= 1.0;
            }
            if i.key_down(egui::Key::D) || i.key_down(egui::Key::ArrowRight) {
                d.x += 1.0;
            }
        });
        if d != Vec2::ZERO {
            view.center += d * dt * 600.0 / view.zoom;
            view.follow = false;
        }
    }
    view.center = view.center.clamp(Pos2::ZERO, egui::pos2(MAP_W as f32, MAP_H as f32));
}

fn pick(xf: &Xf, view: &View, snap: &Snap, p: Pos2) -> Option<u32> {
    let limit = xf.r(0.7, 10.0);
    view.shown
        .iter()
        .filter(|(id, _)| snap.chars.contains_key(id))
        .map(|(id, w)| (*id, (xf.s(*w) - p).length(), snap.chars[id].kind == "person"))
        .filter(|(_, d, _)| *d <= limit)
        // Prefer people over animals when overlapping.
        .min_by(|a, b| (a.1 - if a.2 { 6.0 } else { 0.0 }).total_cmp(&(b.1 - if b.2 { 6.0 } else { 0.0 })))
        .map(|(id, _, _)| id)
}

fn resources(p: &egui::Painter, xf: &Xf, snap: &Snap) {
    let vis = xf.rect.expand(40.0);
    for n in &snap.resources {
        let c = xf.s(egui::pos2(n.x, n.y));
        if !vis.contains(c) {
            continue;
        }
        let amount = (n.amount + n.regen * snap.now.saturating_sub(n.at_ms) as f32 / 60000.0).min(n.max);
        let f = if n.max > 0.0 { (amount / n.max).clamp(0.0, 1.0) } else { 1.0 };
        let alpha = 0.35 + 0.65 * f;
        let scale = 0.6 + 0.4 * f;
        match n.kind.as_str() {
            "berry_bush" => {
                let r = xf.r(0.36 * scale, 2.5);
                p.circle_filled(c, r, a(Color32::from_rgb(46, 110, 52), alpha));
                let dots = (f * 4.0).ceil() as usize;
                for k in 0..dots {
                    let ang = k as f32 * 1.9 + n.id as f32;
                    let off = egui::vec2(ang.cos(), ang.sin()) * r * 0.5;
                    let col = if k % 2 == 0 { Color32::from_rgb(214, 40, 70) } else { Color32::from_rgb(150, 60, 190) };
                    p.circle_filled(c + off, (r * 0.28).max(1.2), a(col, alpha));
                }
            }
            "tree" => {
                let r = xf.r(0.46 * scale, 3.0);
                p.circle_filled(c + egui::vec2(r * 0.15, r * 0.2), r, Color32::from_black_alpha((70.0 * alpha) as u8));
                p.circle_filled(c, r, a(Color32::from_rgb(30, 74, 38), alpha));
                p.circle_filled(c - egui::vec2(r * 0.25, r * 0.25), r * 0.5, a(Color32::from_rgb(56, 112, 58), alpha));
            }
            "boulder" => {
                let r = xf.r(0.34 * scale, 2.5);
                p.circle_filled(c, r, a(Color32::from_rgb(146, 146, 150), alpha));
                p.circle_stroke(c, r, Stroke::new(1.0, a(Color32::from_rgb(78, 78, 84), alpha)));
            }
            "reeds" => {
                let h = xf.r(0.4 * scale, 3.0);
                let col = a(Color32::from_rgb(170, 214, 110), alpha);
                for k in -1..=1 {
                    let x = k as f32 * h * 0.35;
                    p.line_segment([c + egui::vec2(x, h * 0.5), c + egui::vec2(x * 1.4, -h * 0.6)], Stroke::new(1.5, col));
                }
            }
            "fishing_spot" => {
                let r = xf.r(0.38, 3.0);
                p.circle_stroke(c, r, Stroke::new(1.5, a(Color32::from_rgb(200, 235, 255), alpha)));
                if f > 0.5 {
                    p.circle_stroke(c, r * 0.5, Stroke::new(1.0, a(Color32::from_rgb(200, 235, 255), alpha)));
                }
            }
            _ => {
                p.circle_filled(c, xf.r(0.2, 2.0), a(Color32::WHITE, alpha));
            }
        }
    }
}

fn structures(p: &egui::Painter, xf: &Xf, snap: &Snap, t: f32) {
    for s in &snap.structures {
        let c = xf.s(egui::pos2(s.x, s.y));
        if !xf.rect.expand(40.0).contains(c) {
            continue;
        }
        match s.kind.as_str() {
            "campfire" => {
                let r = xf.r(0.35, 3.0);
                for k in 0..6 {
                    let ang = k as f32 * std::f32::consts::TAU / 6.0;
                    p.circle_filled(c + egui::vec2(ang.cos(), ang.sin()) * r, r * 0.3, Color32::from_rgb(110, 105, 100));
                }
                let flick = 0.8 + 0.2 * ((t * 9.0 + s.id as f32).sin() * (t * 5.3).cos());
                p.circle_filled(c, r * 0.75 * flick, Color32::from_rgb(255, 140, 30));
                p.circle_filled(c, r * 0.4 * flick, Color32::from_rgb(255, 225, 120));
            }
            "shelter" => {
                let h = xf.r(0.55, 4.0);
                let r = Rect::from_center_size(c, egui::vec2(h * 2.0, h * 2.0));
                p.rect_filled(r.translate(egui::vec2(2.0, 2.0)), 2.0, Color32::from_black_alpha(80));
                p.rect_filled(r, 2.0, Color32::from_rgb(136, 92, 52));
                p.line_segment([r.left_top(), r.right_bottom()], Stroke::new(1.0, Color32::from_rgb(92, 60, 32)));
                p.line_segment([r.right_top(), r.left_bottom()], Stroke::new(1.0, Color32::from_rgb(92, 60, 32)));
                p.rect_stroke(r, 2.0, Stroke::new(1.2, Color32::from_rgb(70, 44, 22)), StrokeKind::Inside);
            }
            "storage" => {
                let h = xf.r(0.35, 3.0);
                let r = Rect::from_center_size(c, egui::vec2(h * 2.0, h * 2.0));
                p.rect_filled(r, 1.5, Color32::from_rgb(196, 160, 100));
                p.rect_stroke(r, 1.5, Stroke::new(1.2, Color32::from_rgb(110, 80, 40)), StrokeKind::Inside);
                p.line_segment([r.left_center(), r.right_center()], Stroke::new(1.0, Color32::from_rgb(110, 80, 40)));
            }
            "remains" => {
                let h = xf.r(0.3, 3.0);
                let st = Stroke::new(2.0, Color32::from_rgb(200, 200, 200));
                p.line_segment([c - egui::vec2(h, h), c + egui::vec2(h, h)], st);
                p.line_segment([c + egui::vec2(-h, h), c + egui::vec2(h, -h)], st);
            }
            _ => {
                p.rect_filled(Rect::from_center_size(c, egui::vec2(6.0, 6.0)), 1.0, Color32::WHITE);
            }
        }
    }
}

fn fire_glow(p: &egui::Painter, xf: &Xf, snap: &Snap, t: f32, dark: f32) {
    if dark <= 0.05 {
        return;
    }
    for s in snap.structures.iter().filter(|s| s.kind == "campfire") {
        let c = xf.s(egui::pos2(s.x, s.y));
        let flick = 0.92 + 0.08 * (t * 7.0 + s.id as f32).sin();
        for k in (1..=5).rev() {
            let r = xf.r(0.9 * k as f32 * flick, 4.0 * k as f32);
            p.circle_filled(c, r, Color32::from_rgba_unmultiplied(255, 150, 60, (dark * 14.0) as u8));
        }
        p.circle_filled(c, xf.r(0.3, 2.5), Color32::from_rgb(255, 200, 90));
    }
}

fn selected_overlays(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap) {
    let Some(id) = view.selected else { return };
    let Some(pos) = view.shown.get(&id).copied() else { return };
    let col = person_color(id);
    if let Some(b) = snap.bodies.get(&id) {
        let mut prev = xf.s(pos);
        for w in &b.path {
            let q = xf.s(egui::pos2(w.x, w.y));
            dashed(p, prev, q, Stroke::new(1.5, a(col, 0.8)));
            prev = q;
        }
        if let Some(w) = b.path.last() {
            p.circle_stroke(xf.s(egui::pos2(w.x, w.y)), 4.0, Stroke::new(1.5, a(col, 0.9)));
        }
    }
    if let Some(act) = snap.activity.get(&id) {
        if act.target.class != 0 {
            let tp = if act.target.class == 3 {
                view.shown.get(&(act.target.id as u32)).copied().unwrap_or(egui::pos2(act.target.x, act.target.y))
            } else {
                egui::pos2(act.target.x, act.target.y)
            };
            let q = xf.s(tp);
            p.circle_stroke(q, xf.r(0.6, 6.0), Stroke::new(1.5, Color32::from_rgb(255, 230, 120)));
        }
    }
    if let Some(c) = snap.chars.get(&id) {
        if c.kind == "person" {
            let h = xf.s(egui::pos2(c.home_x, c.home_y));
            p.text(h, Align2::CENTER_CENTER, "⌂", FontId::proportional(16.0), a(col, 0.9));
        }
    }
}

fn dashed(p: &egui::Painter, a: Pos2, b: Pos2, st: Stroke) {
    let d = b - a;
    let len = d.length();
    if len < 1.0 {
        return;
    }
    let dir = d / len;
    let mut s = 0.0;
    while s < len {
        let e = (s + 5.0).min(len);
        p.line_segment([a + dir * s, a + dir * e], st);
        s += 9.0;
    }
}

fn creatures(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap) {
    let mut ids: Vec<u32> = view.shown.keys().copied().collect();
    // Animals first, people on top, the selected one last.
    ids.sort_by_key(|id| (Some(*id) == view.selected, snap.chars.get(id).map(|c| c.kind == "person").unwrap_or(false), *id));
    for id in ids {
        let Some(c) = snap.chars.get(&id) else { continue };
        let pos = xf.s(view.shown[&id]);
        if !xf.rect.expand(30.0).contains(pos) {
            continue;
        }
        let (r, fill, edge) = match c.kind.as_str() {
            "person" if snap.is_child(c) => (xf.r(0.3, 4.0), person_color(id), Color32::from_rgb(20, 20, 24)),
            "person" => (xf.r(0.42, 5.5), person_color(id), Color32::from_rgb(20, 20, 24)),
            "deer" => (xf.r(0.3, 3.5), Color32::from_rgb(196, 150, 96), Color32::from_rgb(90, 64, 36)),
            "wolf" => (xf.r(0.36, 4.0), Color32::from_rgb(70, 72, 78), Color32::from_rgb(170, 40, 40)),
            _ => (xf.r(0.3, 3.5), Color32::WHITE, Color32::BLACK),
        };
        p.circle_filled(pos + egui::vec2(1.0, 1.5), r, Color32::from_black_alpha(90));
        p.circle_filled(pos, r, fill);
        p.circle_stroke(pos, r, Stroke::new(1.3, edge));
        if let Some(b) = snap.bodies.get(&id) {
            let v = egui::vec2(b.vx, b.vy);
            if b.next_ms > snap.now && v.length() > 0.01 {
                let dir = v.normalized();
                p.circle_filled(pos + dir * r * 0.55, (r * 0.22).max(1.2), Color32::from_black_alpha(150));
            }
        }
        if Some(id) == view.selected {
            p.circle_stroke(pos, r + 4.0, Stroke::new(2.0, Color32::from_rgb(255, 230, 120)));
        }
    }
}

fn labels(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap) {
    for (id, w) in &view.shown {
        let Some(c) = snap.chars.get(id) else { continue };
        let pos = xf.s(*w);
        if !xf.rect.expand(30.0).contains(pos) {
            continue;
        }
        let person = c.kind == "person";
        let r = if person { xf.r(0.42, 5.5) } else { xf.r(0.33, 3.5) };
        let selected = Some(*id) == view.selected;
        // Health bar.
        if let Some(v) = snap.vitals.get(id) {
            let hp = need(v.hp, v.hp_rate, v.at_ms, snap.now, v.max_hp);
            let frac = if v.max_hp > 0.0 { hp / v.max_hp } else { 0.0 };
            if person || frac < 0.999 {
                let w = (r * 2.4).max(18.0);
                let bar = Rect::from_min_size(pos + egui::vec2(-w / 2.0, r + 3.0), egui::vec2(w, 3.0));
                p.rect_filled(bar.expand(1.0), 1.0, Color32::from_black_alpha(170));
                let col = if frac > 0.6 { Color32::from_rgb(90, 210, 90) } else if frac > 0.3 { Color32::from_rgb(230, 190, 60) } else { Color32::from_rgb(230, 70, 60) };
                p.rect_filled(Rect::from_min_size(bar.min, egui::vec2(w * frac.clamp(0.0, 1.0), 3.0)), 1.0, col);
            }
        }
        if !person {
            continue;
        }
        let name = p.layout_no_wrap(c.name.clone(), FontId::proportional(if selected { 14.0 } else { 12.5 }), Color32::WHITE);
        let at = pos - egui::vec2(name.size().x / 2.0, r + 4.0 + name.size().y);
        let bg = Rect::from_min_size(at, name.size()).expand2(egui::vec2(4.0, 1.0));
        p.rect_filled(bg, 3.0, Color32::from_black_alpha(if selected { 200 } else { 140 }));
        p.galley(at, name, Color32::WHITE);
        if xf.zoom >= 7.0 || selected {
            if let Some(act) = snap.activity.get(id) {
                let g = p.layout_no_wrap(act.label.clone(), FontId::proportional(11.0), Color32::from_rgb(235, 235, 210));
                let at = pos + egui::vec2(-g.size().x / 2.0, r + 8.0);
                p.rect_filled(Rect::from_min_size(at, g.size()).expand2(egui::vec2(3.0, 0.5)), 3.0, Color32::from_black_alpha(110));
                p.galley(at, g, Color32::WHITE);
            }
        }
    }
}

/// Text inside the curly quotes of a speech chronicle line, else the whole line.
pub fn spoken(text: &str) -> &str {
    if let (Some(s), Some(e)) = (text.find('“'), text.rfind('”')) {
        if e > s {
            return &text[s + '“'.len_utf8()..e];
        }
    }
    text
}

fn speech(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap) {
    let mut done = std::collections::HashSet::new();
    for row in view.chronicle.iter().take_while(|r| snap.now.saturating_sub(r.at_ms) < SPEECH_MS * 3) {
        let age = snap.now.saturating_sub(row.at_ms);
        if row.kind != "speech" || age >= SPEECH_MS || !done.insert(row.a) {
            continue;
        }
        let Some(w) = view.shown.get(&row.a) else { continue };
        let pos = xf.s(*w);
        if !xf.rect.contains(pos) {
            continue;
        }
        let fade = (1.0 - (age as f32 - (SPEECH_MS as f32 - 1000.0)) / 1000.0).clamp(0.0, 1.0);
        let mut text = spoken(&row.text).to_string();
        if row.b != 0 {
            text = format!("→ {}: {text}", snap.name(row.b));
        }
        let g = p.layout(text, FontId::proportional(12.5), a(Color32::from_rgb(25, 25, 30), fade), 220.0);
        let size = g.size() + egui::vec2(12.0, 8.0);
        let r = xf.r(0.42, 5.5);
        let bottom = pos - egui::vec2(0.0, r + 24.0);
        let rect = Rect::from_min_size(bottom - egui::vec2(size.x / 2.0, size.y), size);
        let fill = a(Color32::from_rgb(250, 248, 238), 0.95 * fade);
        p.add(egui::Shape::convex_polygon(
            vec![bottom + egui::vec2(-6.0, -1.0), bottom + egui::vec2(6.0, -1.0), bottom + egui::vec2(0.0, 8.0)],
            fill,
            Stroke::NONE,
        ));
        p.rect_filled(rect, 6.0, fill);
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, a(person_color(row.a), fade)), StrokeKind::Inside);
        p.galley(rect.min + egui::vec2(6.0, 4.0), g, Color32::BLACK);
    }
}
