//! The map: pixel-art terrain, resources, structures and creatures (y-sorted sprites),
//! speech, day/night and seasons, drawn with the egui painter in the central area
//! (pan: drag/WASD, zoom: wheel, click: select).

use crate::art::{hash2, Art, Season};
use crate::state::{need, person_color, world_tiles, EffectKind, Snap, View};
use crate::terrain::TILE_PX;
use bevy_egui::egui::{self, Align2, Color32, FontId, Pos2, Rect, Stroke, StrokeKind, Vec2};
use std::collections::HashMap;

const SPEECH_MS: u64 = 6000;
/// `artifact.holder` for items held by a structure (STRUCTURE_BIT | structure id).
pub const SIGN_BIT: u64 = 1 << 40;

/// A tooltip rectangle near the pointer, kept inside the map area.
fn fit_tip(bounds: Rect, p: Pos2, size: Vec2, pad: f32) -> Rect {
    let mut r = Rect::from_min_size(p + egui::vec2(14.0, 10.0), size).expand(pad);
    if r.right() > bounds.right() {
        r = r.translate(egui::vec2(bounds.right() - r.right() - 4.0, 0.0));
    }
    if r.bottom() > bounds.bottom() {
        r = r.translate(egui::vec2(0.0, p.y - 10.0 - r.bottom()));
    }
    r
}

fn p_glow(p: &egui::Painter, c: Pos2, r: f32, dark: f32) {
    p.circle_filled(c, r, Color32::from_rgba_unmultiplied(255, 170, 70, (dark * 12.0) as u8));
}

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
    /// Screen points per sprite pixel: true scale (16 px per tile), with a floor so that
    /// sprites stay readable when zoomed out.
    fn px(&self, grow: f32, min: f32) -> f32 {
        (self.zoom / TILE_PX as f32 * grow).max(min)
    }
}

fn a(c: Color32, alpha: f32) -> Color32 {
    let [r, g, b, _] = c.to_array();
    Color32::from_rgba_unmultiplied(r, g, b, (alpha.clamp(0.0, 1.0) * 255.0) as u8)
}

fn tint(alpha: f32) -> Color32 {
    Color32::from_white_alpha((alpha.clamp(0.0, 1.0) * 255.0) as u8)
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

/// Where each creature was drawn this frame: feet and sprite top (screen points).
type Placed = HashMap<u32, (Pos2, f32)>;

pub fn central(ctx: &egui::Context, view: &mut View, snap: &Snap, t: f32) {
    egui::CentralPanel::default().frame(egui::Frame::NONE.fill(Color32::from_rgb(16, 22, 28))).show(ctx, |ui| {
        let rect = ui.max_rect();
        let resp = ui.allocate_rect(rect, egui::Sense::click_and_drag());
        // Fit the whole valley once the terrain has arrived (and on request).
        let fit = ui.input(|i| i.key_pressed(egui::Key::Home)) && !ui.ctx().wants_keyboard_input();
        if (!view.fitted && view.terrain.is_some() && rect.width() > 50.0) || fit {
            view.zoom = (rect.width().min(rect.height()) / world_tiles().max_elem() * 0.96).max(2.0);
            view.center = (world_tiles() / 2.0).to_pos2();
            view.follow = false;
            view.fitted = true;
        }
        input(ui, &resp, view, rect);
        let xf = Xf { rect, center: view.center, zoom: view.zoom };
        let painter = ui.painter_at(rect);
        let season = view.season(snap);

        // Terrain: the coarsest level that still has about one texel per screen point.
        if let Some(terrain) = &view.terrain {
            let r = Rect::from_min_max(xf.s(Pos2::ZERO), xf.s(world_tiles().to_pos2()));
            let level = terrain.levels.iter().rev().find(|(_, s)| *s as f32 >= xf.zoom * 0.9).unwrap_or(&terrain.levels[0]);
            painter.image(level.0.id(), r, Rect::from_min_max(Pos2::ZERO, egui::pos2(1.0, 1.0)), Color32::WHITE);
            painter.rect_stroke(r, 0.0, Stroke::new(1.0, Color32::from_black_alpha(160)), StrokeKind::Outside);
            if xf.zoom >= 8.0 {
                glints(&painter, &xf, &terrain.water, t, season);
            }
        } else {
            painter.text(rect.center(), Align2::CENTER_CENTER, "waiting for the world…", FontId::proportional(18.0), Color32::GRAY);
        }

        selected_overlays(&painter, &xf, view, snap);
        let (placed, signs) = match view.art.take() {
            Some(mut art) => {
                let out = sprites(ctx, &painter, &xf, view, &mut art, snap, t, season);
                view.art = Some(art);
                out
            }
            None => (Placed::new(), Vec::new()),
        };

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
        if dark > 0.05 {
            for id in &snap.torches {
                if let Some((feet, top)) = placed.get(id) {
                    let c = egui::pos2(feet.x, (feet.y + top) / 2.0);
                    let flick = 0.93 + 0.07 * (t * 9.0 + *id as f32).sin();
                    for k in (1..=4).rev() {
                        let r = xf.r(0.7 * k as f32 * flick, 5.0 * k as f32);
                        p_glow(&painter, c, r, dark);
                    }
                    painter.circle_filled(c + egui::vec2((feet.y - top) * 0.3, -(feet.y - top) * 0.2), 2.5, Color32::from_rgb(255, 200, 90));
                }
            }
        }
        labels(&painter, &xf, view, snap, &placed, t);
        combat(&painter, &xf, view, snap, &placed, t);
        let trade_tip = trades(&painter, snap, &placed, resp.hover_pos());
        speech(&painter, &xf, view, snap, &placed);

        // Signs: hover shows the text; click pins it open.
        let over_sign = resp.hover_pos().and_then(|p| signs.iter().find(|(_, r)| r.expand(2.0).contains(p)).map(|(id, _)| *id));
        if let (Some(sid), Some(p)) = (over_sign, resp.hover_pos()) {
            if let Some(a) = snap.artifacts.iter().find(|a| a.holder == SIGN_BIT | sid) {
                let g = painter.layout(format!("{}\n— {}", a.text, a.author_name), FontId::proportional(12.5), Color32::from_rgb(40, 30, 20), 260.0);
                let r = fit_tip(rect, p, g.size(), 6.0);
                painter.rect_filled(r, 4.0, Color32::from_rgb(232, 214, 170));
                painter.rect_stroke(r, 4.0, Stroke::new(1.5, Color32::from_rgb(110, 80, 44)), StrokeKind::Inside);
                painter.galley(r.min + egui::vec2(6.0, 6.0), g, Color32::BLACK);
                ctx.set_cursor_icon(egui::CursorIcon::PointingHand);
            }
        }
        if resp.clicked() {
            if let Some(sid) = over_sign {
                view.open_sign = Some(sid);
            }
        }

        if let (Some(text), Some(p)) = (&trade_tip, resp.hover_pos()) {
            let g = painter.layout(text.clone(), FontId::proportional(12.5), Color32::from_rgb(40, 30, 20), 260.0);
            let r = fit_tip(rect, p, g.size(), 6.0);
            painter.rect_filled(r, 4.0, Color32::from_rgb(236, 222, 180));
            painter.rect_stroke(r, 4.0, Stroke::new(1.5, Color32::from_rgb(120, 90, 50)), StrokeKind::Inside);
            painter.galley(r.min + egui::vec2(6.0, 6.0), g, Color32::BLACK);
        }

        // Selection and hover.
        let hovered = if over_sign.is_some() || trade_tip.is_some() { None } else { resp.hover_pos().and_then(|p| pick(&placed, snap, p)) };
        if let (Some(id), Some(p)) = (hovered, resp.hover_pos()) {
            let mut s = snap.name(id);
            if let Some(act) = snap.activity.get(&id) {
                s.push_str(&format!(" — {}", act.label));
            }
            let g = painter.layout_no_wrap(s, FontId::proportional(13.0), Color32::WHITE);
            let r = fit_tip(rect, p, g.size(), 4.0);
            painter.rect_filled(r, 4.0, Color32::from_black_alpha(200));
            painter.galley(r.min + egui::vec2(4.0, 4.0), g, Color32::WHITE);
            ctx.set_cursor_icon(egui::CursorIcon::PointingHand);
        }
        if resp.clicked() || resp.double_clicked() {
            let at = resp.interact_pointer_pos().or(resp.hover_pos());
            if let Some(id) = at.and_then(|p| pick(&placed, snap, p)) {
                view.selected = Some(id);
                if resp.double_clicked() {
                    view.follow = true;
                }
            }
        }

        minimap(ui, &painter, rect, &xf, view, snap, t);

        // Legend / hint.
        let fit_btn = Rect::from_min_size(rect.right_top() + egui::vec2(-74.0, 8.0), egui::vec2(66.0, 22.0));
        if ui.put(fit_btn, egui::Button::new("Fit map")).clicked() {
            view.fitted = false;
        }
        let hint = "drag or WASD to pan · wheel to zoom · click to inspect · double-click to follow · Home to fit";
        painter.text(rect.left_bottom() + egui::vec2(10.0, -8.0), Align2::LEFT_BOTTOM, hint, FontId::proportional(11.5), Color32::from_white_alpha(150));
    });
}

/// Brief sparkles on visible water tiles.
fn glints(p: &egui::Painter, xf: &Xf, water: &[(u16, u16)], t: f32, season: Season) {
    let texel = xf.zoom / TILE_PX as f32;
    let vis = xf.rect.expand(xf.zoom);
    let col = if season == Season::Winter { (235, 245, 255) } else { (225, 242, 255) };
    for &(tx, ty) in water {
        let base = xf.s(egui::pos2(tx as f32, ty as f32));
        if !vis.contains(base) {
            continue;
        }
        for k in 0..2 {
            let h = hash2(tx as i32, ty as i32, 40 + k);
            let phase = t * 1.4 + h * 40.0;
            let s = phase.sin().max(0.0).powi(8);
            if s < 0.05 {
                continue;
            }
            let lx = (hash2(tx as i32, ty as i32, 50 + k) * 13.0).floor() + 1.0;
            let ly = (hash2(tx as i32, ty as i32, 60 + k) * 14.0).floor() + 1.0;
            let r = Rect::from_min_size(base + egui::vec2(lx * texel, ly * texel), egui::vec2(texel * 3.0, texel));
            p.rect_filled(r, 0.0, Color32::from_rgba_unmultiplied(col.0, col.1, col.2, (s * 200.0) as u8));
        }
    }
}

fn pick(placed: &Placed, snap: &Snap, p: Pos2) -> Option<u32> {
    placed
        .iter()
        .filter_map(|(id, (feet, top))| {
            let r = Rect::from_min_max(egui::pos2(feet.x - (feet.y - top) * 0.45, *top), egui::pos2(feet.x + (feet.y - top) * 0.45, feet.y + 2.0)).expand(3.0);
            r.contains(p).then(|| (*id, (r.center() - p).length(), snap.chars.get(id).is_some_and(|c| c.kind == "person")))
        })
        // Prefer people over animals when overlapping.
        .min_by(|a, b| (a.1 - if a.2 { 12.0 } else { 0.0 }).total_cmp(&(b.1 - if b.2 { 12.0 } else { 0.0 })))
        .map(|(id, _, _)| id)
}

enum Item {
    Resource(usize),
    Structure(usize),
    Creature(u32),
}

#[allow(clippy::too_many_arguments)]
fn sprites(ctx: &egui::Context, p: &egui::Painter, xf: &Xf, view: &View, art: &mut Art, snap: &Snap, t: f32, season: Season) -> (Placed, Vec<(u64, Rect)>) {
    let vis = xf.rect.expand(60.0);
    let mut items: Vec<(f32, Item)> = Vec::with_capacity(snap.resources.len() + snap.bodies.len() + snap.structures.len());
    for (i, n) in snap.resources.iter().enumerate() {
        if vis.contains(xf.s(egui::pos2(n.x, n.y))) {
            items.push((n.y, Item::Resource(i)));
        }
    }
    for (i, s) in snap.structures.iter().enumerate() {
        if vis.contains(xf.s(egui::pos2(s.x, s.y))) {
            items.push((s.y, Item::Structure(i)));
        }
    }
    for (id, w) in &view.shown {
        if snap.chars.contains_key(id) && vis.contains(xf.s(*w)) {
            items.push((w.y, Item::Creature(*id)));
        }
    }
    items.sort_by(|a, b| a.0.total_cmp(&b.0));
    let mut placed = Placed::new();
    let mut signs = Vec::new();
    let shadow = |p: &egui::Painter, feet: Pos2, w: f32| {
        p.add(egui::Shape::ellipse_filled(feet + egui::vec2(0.0, -w * 0.05), egui::vec2(w * 0.36, w * 0.11), Color32::from_black_alpha(80)));
    };
    for (_, item) in items {
        match item {
            Item::Resource(i) => {
                let n = &snap.resources[i];
                let feet = xf.s(egui::pos2(n.x, n.y + 0.4));
                let amount = snap.resource_amount(n);
                let f = if n.max > 0.0 { (amount / n.max).clamp(0.0, 1.0) } else { 1.0 };
                let s = xf.px(1.0, 0.45);
                match n.kind.as_str() {
                    "berry_bush" => {
                        let sheet = &art.bushes[&season];
                        shadow(p, feet, sheet.w as f32 * s);
                        sheet.draw(p, (f * 3.0).round() as usize, feet, s, n.id % 2 == 0, Color32::WHITE);
                    }
                    "tree" => {
                        let sheet = &art.trees[&season];
                        let s = xf.px(1.25, 0.6) * (0.75 + 0.25 * f);
                        shadow(p, feet, sheet.w as f32 * s * 1.2);
                        sheet.draw(p, n.id as usize % 4, feet, s, n.id % 3 == 0, tint(0.55 + 0.45 * f));
                    }
                    "boulder" => {
                        let s = s * (0.7 + 0.3 * f);
                        art.boulder.draw(p, 0, feet, s, n.id % 2 == 0, tint(0.6 + 0.4 * f));
                    }
                    "reeds" => {
                        let frame = ((t * 1.5 + n.id as f32 * 0.7) as usize) % 2;
                        art.reeds.draw(p, frame, feet, s, false, tint(0.5 + 0.5 * f));
                    }
                    "fishing_spot" => {
                        let frame = ((t * 2.5 + n.id as f32) as usize) % 4;
                        art.ripples.draw(p, frame, feet, s.max(0.8), false, tint(0.35 + 0.65 * f));
                    }
                    _ => {
                        p.circle_filled(feet, xf.r(0.2, 2.0), Color32::WHITE);
                    }
                }
            }
            Item::Structure(i) => {
                let st = &snap.structures[i];
                let feet = xf.s(egui::pos2(st.x, st.y + 0.45));
                let s = xf.px(1.1, 0.9);
                match st.kind.as_str() {
                    "campfire" => {
                        let frame = ((t * 8.0 + st.id as f32) as usize) % 4;
                        art.campfire.draw(p, frame, feet, s, false, Color32::WHITE);
                    }
                    "shelter" => {
                        shadow(p, feet, art.shelter.w as f32 * s * 1.3);
                        art.shelter.draw(p, 0, feet, s * 1.3, false, Color32::WHITE);
                    }
                    "storage" => {
                        shadow(p, feet, art.storage.w as f32 * s);
                        art.storage.draw(p, 0, feet, s, false, Color32::WHITE);
                    }
                    "remains" => {
                        art.remains.draw(p, 0, feet, s, false, Color32::WHITE);
                    }
                    "sign" => {
                        shadow(p, feet, art.sign.w as f32 * s * 0.6);
                        let r = art.sign.draw(p, 0, feet, s, false, Color32::WHITE);
                        signs.push((st.id, r));
                    }
                    _ => {
                        p.rect_filled(Rect::from_center_size(feet, egui::vec2(6.0, 6.0)), 1.0, Color32::WHITE);
                    }
                }
            }
            Item::Creature(id) => {
                let c = &snap.chars[&id];
                let w = view.shown[&id];
                let feet = xf.s(egui::pos2(w.x, w.y + 0.35));
                let moving = snap.bodies.get(&id).is_some_and(|b| b.next_ms > snap.now && (b.vx.abs() + b.vy.abs()) > 0.01);
                let flip = view.facing.get(&id).copied().unwrap_or(hash2(id as i32, 0, 77) > 0.5);
                let hurt = snap.vitals.get(&id).is_some_and(|v| v.hurt_ms > 0 && snap.now.saturating_sub(v.hurt_ms) < 500);
                let color = if hurt { Color32::from_rgb(255, 120, 120) } else { Color32::WHITE };
                let phase = t * 7.0 + id as f32 * 0.37;
                let act = snap.activity.get(&id);
                if act.is_some_and(|a| a.skill == "dodge") {
                    if let Some(b) = snap.bodies.get(&id).filter(|b| b.next_ms > snap.now) {
                        let dir = egui::vec2(b.vx, b.vy).normalized();
                        let h = xf.px(1.15, 1.35) * 16.0;
                        for k in 1..=4 {
                            let at = feet - dir * (k as f32 * h * 0.28) - egui::vec2(0.0, h * 0.45);
                            p.add(egui::Shape::ellipse_filled(at, egui::vec2(h * 0.22, h * 0.3), Color32::from_white_alpha((70 - k * 14) as u8)));
                        }
                        for k in -1..=1 {
                            let off = egui::vec2(-dir.y, dir.x) * (k as f32 * h * 0.18) - egui::vec2(0.0, h * 0.45);
                            p.line_segment([feet + off - dir * h * 0.3, feet + off - dir * h * 1.1], Stroke::new(1.5, Color32::from_white_alpha(90)));
                        }
                    }
                }
                let rect = match c.kind.as_str() {
                    "person" => {
                        let asleep = snap.activity.get(&id).is_some_and(|a| a.skill == "sleep");
                        let s = xf.px(1.15, 1.35) * if snap.is_child(c) { 0.72 } else { 1.0 };
                        let frame = if asleep {
                            5
                        } else if moving {
                            1 + (phase as usize) % 4
                        } else {
                            0
                        };
                        let sheet = art.person(ctx, id, person_color(id));
                        shadow(p, feet, sheet.w as f32 * s);
                        let r = sheet.draw(p, frame, feet, s, flip, color);
                        if asleep {
                            let k = (t * 0.8 + id as f32 * 0.3).fract();
                            let z = r.center_top() + egui::vec2(r.width() * 0.2 + k * 6.0, -k * 12.0);
                            p.text(z, Align2::CENTER_BOTTOM, "z", FontId::proportional(10.0 + k * 5.0), Color32::from_white_alpha(((1.0 - k) * 230.0) as u8));
                        }
                        r
                    }
                    kind => {
                        let s = xf.px(1.0, 1.0);
                        let sheet = if kind == "wolf" {
                            &art.wolf
                        } else if hash2(id as i32, 1, 78) > 0.5 {
                            &art.deer_antlers
                        } else {
                            &art.deer
                        };
                        let frame = if moving { [1, 2, 3, 2][(phase as usize) % 4] } else { 0 };
                        shadow(p, feet, sheet.w as f32 * s);
                        sheet.draw(p, frame, feet, s, flip, color)
                    }
                };
                if act.is_some_and(|a| a.skill == "block") {
                    let side = if flip { -1.0 } else { 1.0 };
                    shield(p, egui::pos2(rect.center().x + side * rect.width() * 0.32, rect.center().y + rect.height() * 0.08), (rect.height() * 0.42).max(9.0));
                }
                if Some(id) == view.selected {
                    let pulse = 1.0 + 0.12 * (t * 4.0).sin();
                    p.add(egui::Shape::ellipse_stroke(
                        feet,
                        egui::vec2(rect.width() * 0.5 * pulse, rect.width() * 0.17 * pulse),
                        Stroke::new(2.0, Color32::from_rgb(255, 230, 120)),
                    ));
                }
                placed.insert(id, (feet, rect.top()));
            }
        }
    }
    (placed, signs)
}

fn labels(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap, placed: &Placed, t: f32) {
    let name_alpha = ((xf.zoom - 2.0) / 3.0).clamp(0.45, 1.0);
    let act_alpha = ((xf.zoom - 8.0) / 3.0).clamp(0.0, 1.0);
    for (id, (feet, top)) in placed {
        let Some(c) = snap.chars.get(id) else { continue };
        let person = c.kind == "person";
        let selected = Some(*id) == view.selected;
        let w = ((feet.y - top) * 0.9).max(16.0);
        // Health bar under the feet.
        if let Some(v) = snap.vitals.get(id) {
            let hp = need(v.hp, v.hp_rate, v.at_ms, snap.now, v.max_hp);
            let frac = if v.max_hp > 0.0 { hp / v.max_hp } else { 0.0 };
            if (person && (selected || frac < 0.999 || xf.zoom >= 6.0)) || frac < 0.999 {
                let bar = Rect::from_min_size(*feet + egui::vec2(-w / 2.0, 3.0), egui::vec2(w, 3.0));
                p.rect_filled(bar.expand(1.0), 1.0, Color32::from_black_alpha(170));
                let col = if frac > 0.6 { Color32::from_rgb(90, 210, 90) } else if frac > 0.3 { Color32::from_rgb(230, 190, 60) } else { Color32::from_rgb(230, 70, 60) };
                p.rect_filled(Rect::from_min_size(bar.min, egui::vec2(w * frac.clamp(0.0, 1.0), 3.0)), 1.0, col);
            }
        }
        if !person {
            continue;
        }
        let alpha = if selected { 1.0 } else { name_alpha };
        let name = p.layout_no_wrap(c.name.clone(), FontId::proportional(if selected { 14.0 } else { 12.5 }), a(Color32::WHITE, alpha));
        let at = egui::pos2(feet.x - name.size().x / 2.0, top - 3.0 - name.size().y);
        let bg = Rect::from_min_size(at, name.size()).expand2(egui::vec2(4.0, 1.0));
        p.rect_filled(bg, 3.0, Color32::from_black_alpha(((if selected { 200.0 } else { 140.0 }) * alpha) as u8));
        p.rect_filled(Rect::from_min_size(bg.left_top(), egui::vec2(3.0, bg.height())), 2.0, a(person_color(*id), alpha));
        p.galley(at, name, Color32::WHITE);
        let aa = if selected { 1.0 } else { act_alpha };
        if aa > 0.0 {
            if let Some(act) = snap.activity.get(id) {
                let g = p.layout_no_wrap(act.label.clone(), FontId::proportional(11.0), a(Color32::from_rgb(235, 235, 210), aa));
                let at = *feet + egui::vec2(-g.size().x / 2.0, 8.0);
                p.rect_filled(Rect::from_min_size(at, g.size()).expand2(egui::vec2(3.0, 0.5)), 3.0, Color32::from_black_alpha((110.0 * aa) as u8));
                p.galley(at, g, Color32::WHITE);
            }
        }
    }
    let _ = t;
}

fn speech(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap, placed: &Placed) {
    let mut done = std::collections::HashSet::new();
    for row in view.chronicle.iter().take_while(|r| snap.now.saturating_sub(r.at_ms) < SPEECH_MS * 3) {
        let age = snap.now.saturating_sub(row.at_ms);
        if row.kind != "speech" || age >= SPEECH_MS || !done.insert(row.a) {
            continue;
        }
        let Some((feet, top)) = placed.get(&row.a) else { continue };
        if !xf.rect.contains(*feet) {
            continue;
        }
        let fade = (1.0 - (age as f32 - (SPEECH_MS as f32 - 1000.0)) / 1000.0).clamp(0.0, 1.0);
        let mut text = spoken(&row.text).to_string();
        if row.b != 0 {
            text = format!("→ {}: {text}", snap.name(row.b));
        }
        let g = p.layout(text, FontId::proportional(12.5), a(Color32::from_rgb(25, 25, 30), fade), 220.0);
        let size = g.size() + egui::vec2(12.0, 8.0);
        let bottom = egui::pos2(feet.x, top - 22.0);
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
    view.center = view.center.clamp(Pos2::ZERO, world_tiles().to_pos2());
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

/// Text inside the curly quotes of a speech chronicle line, else the whole line.
pub fn spoken(text: &str) -> &str {
    if let (Some(s), Some(e)) = (text.find('“'), text.rfind('”')) {
        if e > s {
            return &text[s + '“'.len_utf8()..e];
        }
    }
    text
}


fn shield(p: &egui::Painter, c: Pos2, h: f32) {
    let w = h * 0.8;
    let pts = vec![
        c + egui::vec2(-w / 2.0, -h / 2.0),
        c + egui::vec2(w / 2.0, -h / 2.0),
        c + egui::vec2(w / 2.0, h * 0.05),
        c + egui::vec2(0.0, h / 2.0),
        c + egui::vec2(-w / 2.0, h * 0.05),
    ];
    p.add(egui::Shape::convex_polygon(pts.clone(), Color32::from_rgb(150, 110, 70), Stroke::new(1.5, Color32::from_rgb(30, 24, 20))));
    p.line_segment([c + egui::vec2(0.0, -h * 0.42), c + egui::vec2(0.0, h * 0.4)], Stroke::new(1.5, Color32::from_rgb(200, 200, 210)));
    p.line_segment([c + egui::vec2(-w * 0.4, -h * 0.12), c + egui::vec2(w * 0.4, -h * 0.12)], Stroke::new(1.5, Color32::from_rgb(200, 200, 210)));
}

fn center_of(placed: &Placed, id: u32) -> Option<Pos2> {
    placed.get(&id).map(|(feet, top)| egui::pos2(feet.x, (feet.y + top) / 2.0))
}

/// Windup telegraphs, flying spears, strikes and fight markers.
fn combat(p: &egui::Painter, xf: &Xf, view: &View, snap: &Snap, placed: &Placed, t: f32) {
    let now = snap.now;
    for (id, a) in &snap.activity {
        if a.victim == 0 || a.phase != 1 || !(a.skill == "attack" || a.skill == "throw") {
            continue;
        }
        let (Some(from), Some(to)) = (center_of(placed, *id), center_of(placed, a.victim)) else { continue };
        let nominal = if a.skill == "throw" { 800.0 } else { 650.0 };
        let k = (1.0 - a.ends_ms.saturating_sub(now) as f32 / nominal).clamp(0.0, 1.0);
        let (base, hot) = if a.skill == "throw" {
            (Color32::from_rgb(250, 220, 90), Color32::from_rgb(255, 170, 40))
        } else {
            (Color32::from_rgb(255, 140, 90), Color32::from_rgb(255, 60, 50))
        };
        dashed(p, from, to, Stroke::new(1.2, a_(base, 0.45)));
        p.line_segment([from, from.lerp(to, k)], Stroke::new(2.5, a_(hot, 0.9)));
        // Filling ring around the attacker.
        let r = placed.get(id).map(|(f, top)| (f.y - top) * 0.62).unwrap_or(12.0).max(9.0);
        let n = 28;
        let pts: Vec<Pos2> = (0..=((n as f32 * k) as usize))
            .map(|i| {
                let ang = -std::f32::consts::FRAC_PI_2 + i as f32 / n as f32 * std::f32::consts::TAU;
                from + egui::vec2(ang.cos(), ang.sin()) * r
            })
            .collect();
        if pts.len() > 1 {
            p.add(egui::Shape::line(pts, Stroke::new(3.0, a_(hot, 0.95))));
        }
        if a.skill == "throw" {
            let rr = 6.0 + (1.0 - k) * 14.0;
            p.circle_stroke(to, rr, Stroke::new(1.5, a_(hot, 0.9)));
            p.line_segment([to - egui::vec2(rr + 4.0, 0.0), to - egui::vec2(rr - 3.0, 0.0)], Stroke::new(1.5, a_(hot, 0.9)));
            p.line_segment([to + egui::vec2(rr - 3.0, 0.0), to + egui::vec2(rr + 4.0, 0.0)], Stroke::new(1.5, a_(hot, 0.9)));
        }
    }
    for e in &view.effects {
        let k = (now.saturating_sub(e.start_ms) as f32 / e.dur_ms.max(1) as f32).clamp(0.0, 1.0);
        let to = center_of(placed, e.to).unwrap_or(xf.s(e.to_at));
        match e.kind {
            EffectKind::Spear => {
                if now > e.start_ms + e.dur_ms {
                    continue;
                }
                let from = xf.s(e.from) - egui::vec2(0.0, xf.px(1.15, 1.35) * 8.0);
                let at = from.lerp(to, k);
                let dir = (to - from).normalized();
                let len = xf.r(1.0, 16.0);
                p.line_segment([at - dir * len, at], Stroke::new(2.5, Color32::from_rgb(120, 84, 50)));
                p.add(egui::Shape::convex_polygon(
                    vec![at + dir * 6.0, at + egui::vec2(-dir.y, dir.x) * 3.0, at - egui::vec2(-dir.y, dir.x) * 3.0],
                    Color32::from_rgb(210, 210, 220),
                    Stroke::new(1.0, Color32::from_rgb(40, 40, 50)),
                ));
            }
            EffectKind::Slash => {
                let alpha = 1.0 - k;
                let r = xf.r(0.5, 10.0) * (0.8 + k * 0.5);
                for j in 0..3 {
                    let off = (j as f32 - 1.0) * 0.35;
                    let pts: Vec<Pos2> = (0..8)
                        .map(|i| {
                            let ang = -2.3 + off + i as f32 * 0.22;
                            to + egui::vec2(ang.cos(), ang.sin()) * (r + j as f32 * 3.0)
                        })
                        .collect();
                    p.add(egui::Shape::line(pts, Stroke::new(2.0, Color32::from_white_alpha((alpha * 230.0) as u8))));
                }
            }
        }
    }
    for (a, b) in view.fights.keys() {
        let (Some(pa), Some(pb)) = (placed.get(a), placed.get(b)) else { continue };
        let top = pa.1.min(pb.1);
        let c = egui::pos2((pa.0.x + pb.0.x) / 2.0, top - 30.0 + (t * 5.0).sin() * 2.0);
        p.circle_filled(c, 10.0, Color32::from_rgba_unmultiplied(120, 20, 20, 210));
        p.circle_stroke(c, 10.0, Stroke::new(1.5, Color32::from_rgb(255, 190, 120)));
        p.text(c, Align2::CENTER_CENTER, "⚔", FontId::proportional(13.0), Color32::WHITE);
    }
}

fn a_(c: Color32, alpha: f32) -> Color32 {
    a(c, alpha)
}

/// Pending trade offers as scrolls between the two people; returns hover text.
fn trades(p: &egui::Painter, snap: &Snap, placed: &Placed, hover: Option<Pos2>) -> Option<String> {
    let mut tip = None;
    for (k, o) in snap.trades.iter().enumerate() {
        let (Some(pa), Some(pb)) = (placed.get(&o.from), placed.get(&o.to)) else { continue };
        let (ca, cb) = (egui::pos2(pa.0.x, (pa.0.y + pa.1) / 2.0), egui::pos2(pb.0.x, (pb.0.y + pb.1) / 2.0));
        dashed(p, ca, cb, Stroke::new(1.2, Color32::from_rgba_unmultiplied(240, 220, 160, 150)));
        let c = ca.lerp(cb, 0.5) - egui::vec2(0.0, 10.0 + k as f32 * 3.0);
        let body = Rect::from_center_size(c, egui::vec2(14.0, 10.0));
        p.rect_filled(body.expand(1.0), 2.0, Color32::from_rgb(60, 40, 24));
        p.rect_filled(body, 1.5, Color32::from_rgb(238, 222, 176));
        for x in [body.left(), body.right()] {
            p.rect_filled(Rect::from_center_size(egui::pos2(x, c.y), egui::vec2(3.5, 13.0)), 1.5, Color32::from_rgb(196, 160, 104));
        }
        p.line_segment([egui::pos2(body.left() + 3.0, c.y - 1.5), egui::pos2(body.right() - 3.0, c.y - 1.5)], Stroke::new(1.0, Color32::from_rgb(120, 90, 60)));
        p.line_segment([egui::pos2(body.left() + 3.0, c.y + 1.5), egui::pos2(body.right() - 5.0, c.y + 1.5)], Stroke::new(1.0, Color32::from_rgb(120, 90, 60)));
        if hover.is_some_and(|h| body.expand(5.0).contains(h)) {
            tip = Some(format!(
                "{} offers {} {} for {} {} → {}\n{}",
                snap.name(o.from),
                o.give_qty,
                o.give_item,
                o.want_qty,
                o.want_item,
                snap.name(o.to),
                snap.stamp(o.at_ms)
            ));
        }
    }
    tip
}

/// Terrain thumbnail with people by camp colour, wolves, fights and the viewport; click
/// or drag to move the camera.
fn minimap(ui: &egui::Ui, p: &egui::Painter, rect: Rect, xf: &Xf, view: &mut View, snap: &Snap, t: f32) {
    let Some(terrain) = &view.terrain else { return };
    let tiles = world_tiles();
    let side = (rect.width().min(rect.height()) * 0.3).clamp(110.0, 190.0);
    let size = tiles / tiles.max_elem() * side;
    let mm = Rect::from_min_size(rect.right_bottom() - size - egui::vec2(12.0, 12.0), size);
    let resp = ui.interact(mm, egui::Id::new("minimap"), egui::Sense::click_and_drag());
    let to_mm = |w: Pos2| mm.min + (w.to_vec2() / tiles) * size;
    p.rect_filled(mm.expand(3.0), 4.0, Color32::from_rgba_unmultiplied(10, 12, 16, 230));
    let level = terrain.levels.last().unwrap();
    p.image(level.0.id(), mm, Rect::from_min_max(Pos2::ZERO, egui::pos2(1.0, 1.0)), Color32::from_gray(225));
    for s in snap.structures.iter().filter(|s| s.kind == "campfire" || s.kind == "shelter") {
        p.rect_filled(Rect::from_center_size(to_mm(egui::pos2(s.x, s.y)), egui::vec2(2.0, 2.0)), 0.0, Color32::from_rgb(255, 170, 60));
    }
    for (id, w) in &view.shown {
        let Some(c) = snap.chars.get(id) else { continue };
        let at = to_mm(*w);
        match c.kind.as_str() {
            "person" => {
                p.circle_filled(at, 3.0, Color32::from_rgb(16, 16, 20));
                p.circle_filled(at, 2.2, snap.camp_color(*id));
                if Some(*id) == view.selected {
                    p.circle_stroke(at, 5.0 + (t * 4.0).sin(), Stroke::new(1.5, Color32::from_rgb(255, 230, 120)));
                }
            }
            "wolf" => {
                p.circle_filled(at, 1.6, Color32::from_rgb(150, 30, 30));
            }
            _ => {}
        }
    }
    for (a, b) in view.fights.keys() {
        if let (Some(pa), Some(pb)) = (view.shown.get(a), view.shown.get(b)) {
            p.circle_stroke(to_mm(pa.lerp(*pb, 0.5)), 4.0 + (t * 6.0).sin() * 1.5, Stroke::new(1.5, Color32::from_rgb(255, 80, 60)));
        }
    }
    let vis = Rect::from_min_max(to_mm(xf.w(rect.min)), to_mm(xf.w(rect.max))).intersect(mm);
    if vis.is_positive() {
        p.rect_stroke(vis, 1.0, Stroke::new(1.5, Color32::WHITE), StrokeKind::Inside);
    }
    p.rect_stroke(mm.expand(3.0), 4.0, Stroke::new(1.0, Color32::from_gray(90)), StrokeKind::Inside);
    if resp.hovered() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::Crosshair);
    }
    if resp.clicked() || resp.dragged() {
        if let Some(pos) = resp.interact_pointer_pos() {
            view.center = (((pos - mm.min) / size) * tiles).to_pos2();
            view.follow = false;
        }
    }
}
