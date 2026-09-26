//! Top bar, story feed, people list and the character inspector.

use crate::map::darkness;
use crate::net::{Net, Status};
use crate::state::{hhmm, need, person_color, LeftTab, Snap, StoryFilter, Tab, View, LEARNING_TRADE};
use bevy_egui::egui::{self, Color32, RichText};
use living_bindings::*;
use living_rules::graph::{self, Node};
use spacetimedb_sdk::Table;

const WEAK: Color32 = Color32::from_rgb(140, 148, 160);

pub fn top_bar(ctx: &egui::Context, net: &Net, snap: &Snap, view: &mut View) {
    let (fps, frame_ms) = (view.fps, view.frame_ms);
    egui::TopBottomPanel::top("top").show(ctx, |ui| {
        ui.add_space(3.0);
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("Living world").strong().size(16.0));
            let (col, text) = match net.status {
                Status::Live => (Color32::from_rgb(90, 210, 110), "live".to_string()),
                Status::Syncing => (Color32::from_rgb(230, 200, 70), "syncing…".to_string()),
                Status::Connecting => (Color32::from_rgb(230, 200, 70), "connecting…".to_string()),
                Status::Offline => (Color32::from_rgb(230, 80, 70), format!("offline — {}", net.detail)),
            };
            ui.label(RichText::new(format!("● {text}")).color(col))
                .on_hover_text(format!("{}/{} · {fps:.0} fps · ui {frame_ms:.1} ms", net.server, net.db));
            if let Some(w) = &snap.world {
                ui.label(RichText::new(&w.run).color(WEAK));
                ui.separator();
                let h = snap.hour();
                let day = living_rules::day_of(snap.now, w.epoch_ms, snap.day_ms());
                let night = living_rules::is_night(h);
                let icon = if night { "🌙" } else if darkness(h) > 0.0 { "🌇" } else { "☀" };
                ui.label(RichText::new(format!("Day {day}  {}  {icon} {}", hhmm(h), if night { "night" } else { "day" })).strong().size(15.0));
                let season = snap.season();
                let (sicon, scol) = match season {
                    crate::art::Season::Spring => ("🌱", Color32::from_rgb(150, 220, 120)),
                    crate::art::Season::Summer => ("🌞", Color32::from_rgb(250, 210, 90)),
                    crate::art::Season::Autumn => ("🍂", Color32::from_rgb(230, 140, 60)),
                    crate::art::Season::Winter => ("❄", Color32::from_rgb(190, 220, 255)),
                };
                let into = (day.saturating_sub(1) % 2) + 1;
                ui.label(RichText::new(format!("{sicon} {} (day {into}/2)", season.name())).color(scol).strong())
                    .on_hover_text("Eight-day year: two days each of spring, summer, autumn and winter.");
                if w.paused {
                    ui.label(RichText::new("PAUSED").color(Color32::from_rgb(255, 180, 60)).strong());
                }
            }
            if let Some(s) = &snap.stats {
                ui.separator();
                ui.label(format!("👤 {} people", s.alive_people));
                ui.label(format!("🐾 {} animals", s.alive_animals));
                if !snap.expecting.is_empty() {
                    ui.label(RichText::new(format!("👶 {} expecting", snap.expecting.len())).color(Color32::from_rgb(255, 170, 210)));
                }
                if s.deaths > 0 || s.births > 0 {
                    ui.label(RichText::new(format!("† {}  ✚ {}", s.deaths, s.births)).color(WEAK));
                }
                ui.separator();
                let gap_col = if s.max_tick_gap_ms > 100 { Color32::from_rgb(240, 150, 60) } else { WEAK };
                ui.label(RichText::new(format!("ticks {}", s.ticks)).color(WEAK));
                ui.label(RichText::new(format!("max gap {} ms", s.max_tick_gap_ms)).color(gap_col));
                ui.label(RichText::new(format!("evals {}", s.evals)).color(WEAK));
                ui.label(RichText::new(format!("deliberations {}", s.deliberations)).color(WEAK));
            }
            if let Some(fighter) = view.latest_fighter(snap) {
                ui.separator();
                let n = view.fights.len();
                let b = egui::Button::new(RichText::new(format!("⚔ {n} fight{} — jump", if n == 1 { "" } else { "s" })).color(Color32::WHITE))
                    .fill(Color32::from_rgb(130, 30, 30));
                if ui.add(b).on_hover_text("zoom in on the most recent fight and follow a fighter").clicked() {
                    view.selected = Some(fighter);
                    view.follow = true;
                    view.zoom = 28.0;
                    if let Some(p) = view.shown.get(&fighter) {
                        view.center = *p;
                    }
                }
            }
            ui.separator();
            ui.label(RichText::new(format!("{fps:.0} fps · ui {frame_ms:.1} ms")).small().color(WEAK));
        });
        ui.add_space(1.0);
    });
}

fn kind_style(kind: &str, text: &str) -> (&'static str, Color32) {
    match kind {
        "speech" => ("💬", Color32::from_rgb(170, 205, 255)),
        "arrival" => ("👣", Color32::from_rgb(170, 230, 170)),
        "build" => ("🔨", Color32::from_rgb(240, 190, 120)),
        "craft" => ("🔧", Color32::from_rgb(240, 190, 120)),
        "cook" => ("🍖", Color32::from_rgb(240, 170, 110)),
        "death" | "died" => ("☠", Color32::from_rgb(255, 110, 100)),
        "attack" | "fight" | "hurt" => ("⚔", Color32::from_rgb(255, 140, 110)),
        "birth" => ("👶", Color32::from_rgb(160, 240, 200)),
        "family" => ("❤", Color32::from_rgb(255, 160, 200)),
        "learn" => ("💡", Color32::from_rgb(255, 230, 120)),
        "write" => ("✍", Color32::from_rgb(230, 210, 170)),
        "plant" => ("🌱", Color32::from_rgb(150, 220, 120)),
        "give" => ("🎁", Color32::from_rgb(230, 200, 255)),
        "trade" => ("🤝", Color32::from_rgb(250, 214, 140)),
        "time" if text.contains("Night") || text.contains("night") => ("🌙", Color32::from_rgb(160, 160, 230)),
        "time" => ("☀", Color32::from_rgb(255, 225, 130)),
        "mind" | "revise" => ("💭", Color32::from_rgb(210, 180, 255)),
        _ => ("•", Color32::from_rgb(210, 210, 210)),
    }
}

pub fn left(ctx: &egui::Context, view: &mut View, net: &Net, snap: &Snap) {
    egui::SidePanel::left("left").resizable(true).default_width(330.0).min_width(240.0).show(ctx, |ui| {
        ui.add_space(4.0);
        let alive = snap.chars.values().filter(|c| c.kind == "person" && c.alive).count();
        ui.horizontal(|ui| {
            ui.selectable_value(&mut view.left_tab, LeftTab::People, RichText::new(format!("People ({alive})")).strong().size(15.0));
            ui.selectable_value(&mut view.left_tab, LeftTab::Communities, RichText::new(format!("Communities ({})", view.communities.len())).strong().size(15.0));
        });
        if view.left_tab == LeftTab::Communities {
            communities(ui, view, net, snap);
        }
        let mut people: Vec<&Character> = snap.chars.values().filter(|c| c.kind == "person").collect();
        people.sort_by_key(|c| (!c.alive, c.id));
        if view.left_tab != LeftTab::People {
            people.clear();
        }
        let mut clicked = None;
        let height = if view.left_tab == LeftTab::People { ui.available_height() * 0.42 } else { 0.0 };
        egui::ScrollArea::vertical().id_salt("people").max_height(height).auto_shrink([false, true]).show(ui, |ui| {
            for c in people {
                let sel = view.selected == Some(c.id);
                let frame = egui::Frame::new()
                    .inner_margin(egui::Margin::symmetric(6, 3))
                    .corner_radius(4.0)
                    .fill(if sel { Color32::from_rgb(44, 58, 76) } else { Color32::TRANSPARENT });
                let r = frame
                    .show(ui, |ui| {
                        ui.set_width(ui.available_width());
                        ui.horizontal(|ui| {
                            ui.label(RichText::new("●").color(if c.alive { person_color(c.id) } else { Color32::DARK_GRAY }));
                            let mut name = RichText::new(&c.name).strong();
                            if !c.alive {
                                name = name.strikethrough().color(Color32::GRAY);
                            }
                            ui.label(name);
                            if let Some(k) = view.community_of.get(&c.id) {
                                let com = &view.communities[*k];
                                ui.label(RichText::new(&com.name).small().color(com.color));
                            }
                            if !c.alive {
                                ui.label(RichText::new("dead").color(Color32::from_rgb(230, 100, 90)).small());
                            }
                            if snap.is_child(c) {
                                ui.label(RichText::new("child").color(Color32::from_rgb(160, 240, 200)).small());
                            }
                            if snap.literate.contains(&c.id) {
                                ui.label(RichText::new("✍").small().color(Color32::from_rgb(230, 210, 170))).on_hover_text("can read and write");
                            }
                            if snap.expecting.iter().any(|e| e.a == c.id || e.b == c.id) {
                                ui.label(RichText::new("👶").small());
                            }
                            if let Some(m) = view.model_of(c.id) {
                                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                    ui.label(RichText::new(m).small().color(WEAK));
                                });
                            }
                        });
                        let act = snap.activity.get(&c.id).map(|a| a.label.clone()).unwrap_or_else(|| if c.alive { "idle".into() } else { c.cause.clone() });
                        let mood = snap.personas.get(&c.id).map(|p| p.mood.clone()).unwrap_or_default();
                        ui.label(RichText::new(if mood.is_empty() { act } else { format!("{act}  ·  {mood}") }).small().color(Color32::from_rgb(200, 200, 190)));
                    })
                    .response;
                if r.interact(egui::Sense::click()).clicked() {
                    clicked = Some(c.id);
                }
            }
        });
        if let Some(id) = clicked {
            view.select(id, snap, true);
        }
        ui.separator();
        ui.horizontal(|ui| {
            ui.label(RichText::new("Story").strong().size(15.0));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.add_enabled(view.selected.is_some(), egui::Checkbox::new(&mut view.story_only_selected, "selected only"));
            });
        });
        ui.horizontal(|ui| {
            ui.selectable_value(&mut view.story_filter, StoryFilter::All, RichText::new("Everything").small());
            ui.selectable_value(&mut view.story_filter, StoryFilter::LearningTrade, RichText::new("💡 Learning & trade").small())
                .on_hover_text("teaching, learning, writing, planting, gifts and trades");
        });
        let filter = if view.story_only_selected { view.selected } else { None };
        let kinds = view.story_filter;
        let mut clicked = None;
        egui::ScrollArea::vertical().id_salt("story").auto_shrink([false, false]).show(ui, |ui| {
            let rows = view
                .chronicle
                .iter()
                .filter(|r| filter.map_or(true, |id| r.a == id || r.b == id))
                .filter(|r| kinds == StoryFilter::All || LEARNING_TRADE.contains(&r.kind.as_str()))
                .take(400);
            for row in rows {
                let (icon, col) = kind_style(&row.kind, &row.text);
                let fresh = snap.now.saturating_sub(row.at_ms) < 8000;
                let frame = egui::Frame::new()
                    .inner_margin(egui::Margin::symmetric(6, 3))
                    .corner_radius(4.0)
                    .fill(if fresh { Color32::from_rgb(38, 46, 38) } else { Color32::TRANSPARENT });
                let r = frame
                    .show(ui, |ui| {
                        ui.set_width(ui.available_width());
                        ui.horizontal(|ui| {
                            ui.label(RichText::new(icon).color(col));
                            ui.label(RichText::new(snap.stamp(row.at_ms)).small().color(WEAK));
                            if row.a != 0 {
                                let c = if snap.chars.get(&row.a).map(|c| c.kind == "person").unwrap_or(false) { person_color(row.a) } else { WEAK };
                                ui.label(RichText::new(snap.name(row.a)).small().color(c));
                            }
                        });
                        ui.add(egui::Label::new(RichText::new(&row.text).color(col)).wrap());
                    })
                    .response;
                let r = r.interact(egui::Sense::click());
                if r.clicked() && row.a != 0 {
                    clicked = Some((row.a, egui::pos2(row.x, row.y)));
                }
                if row.a != 0 {
                    r.on_hover_cursor(egui::CursorIcon::PointingHand);
                }
            }
            if view.chronicle.is_empty() {
                ui.label(RichText::new("Nothing has happened yet.").color(WEAK));
            }
        });
        if let Some((id, at)) = clicked {
            view.select(id, snap, true);
            if snap.body_pos(id).is_none() && at != egui::Pos2::ZERO {
                view.center = at;
            }
        }
    });
}

fn bar(ui: &mut egui::Ui, label: &str, frac: f32, color: Color32, text: String) {
    ui.horizontal(|ui| {
        ui.add_sized([74.0, 16.0], egui::Label::new(RichText::new(label).color(WEAK)));
        ui.add(egui::ProgressBar::new(frac.clamp(0.0, 1.0)).fill(color).desired_height(14.0).text(RichText::new(text).small().color(Color32::WHITE)));
    });
}

/// A bar for a signed value in [-range, range], centered at zero.
fn signed_bar(ui: &mut egui::Ui, label: &str, v: f32, range: f32) {
    ui.horizontal(|ui| {
        ui.add_sized([60.0, 14.0], egui::Label::new(RichText::new(label).small().color(WEAK)));
        let (rect, _) = ui.allocate_exact_size(egui::vec2(ui.available_width().min(200.0), 10.0), egui::Sense::hover());
        let p = ui.painter();
        p.rect_filled(rect, 3.0, Color32::from_rgb(40, 44, 52));
        let mid = rect.center().x;
        let f = (v / range).clamp(-1.0, 1.0);
        let end = mid + f * rect.width() / 2.0;
        let col = if f >= 0.0 { Color32::from_rgb(90, 190, 120) } else { Color32::from_rgb(220, 90, 80) };
        p.rect_filled(egui::Rect::from_x_y_ranges(mid.min(end)..=mid.max(end), rect.y_range()), 2.0, col);
        p.line_segment([egui::pos2(mid, rect.top()), egui::pos2(mid, rect.bottom())], egui::Stroke::new(1.0, Color32::GRAY));
        ui.label(RichText::new(format!("{v:.0}")).small());
    });
}

pub fn inspector(ctx: &egui::Context, view: &mut View, net: &Net, snap: &Snap) {
    egui::SidePanel::right("inspector").resizable(true).default_width(420.0).min_width(300.0).show(ctx, |ui| {
        let Some(id) = view.selected else {
            ui.add_space(20.0);
            ui.label(RichText::new("Select a character on the map, in the people list or in the story.").color(WEAK));
            return;
        };
        let Some(c) = snap.chars.get(&id).cloned() else {
            ui.label("Unknown character.");
            return;
        };
        let Some(conn) = &net.conn else { return };
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            let col = if c.kind == "person" { person_color(id) } else { WEAK };
            ui.label(RichText::new("●").size(20.0).color(col));
            ui.label(RichText::new(snap.name(id)).size(20.0).strong());
            ui.label(RichText::new(format!("{} #{} · age {:.1}", c.kind, c.id, snap.age_days(&c))).color(WEAK));
            if snap.is_child(&c) {
                ui.label(RichText::new("child").color(Color32::from_rgb(160, 240, 200)));
            }
            if snap.literate.contains(&c.id) {
                ui.label(RichText::new("✍ literate").color(Color32::from_rgb(230, 210, 170)));
            }
            if !c.alive {
                ui.label(RichText::new(format!("died {} ({})", snap.stamp(c.died_ms), c.cause)).color(Color32::from_rgb(230, 100, 90)));
            }
        });
        ui.horizontal(|ui| {
            ui.toggle_value(&mut view.follow, "🎥 Follow");
            if ui.button("⌖ Center").clicked() {
                if let Some(p) = view.shown.get(&id) {
                    view.center = *p;
                }
            }
            if ui.button("✕").on_hover_text("deselect").clicked() {
                view.selected = None;
                view.follow = false;
            }
            if let Some(act) = snap.activity.get(&id) {
                ui.label(RichText::new(format!("▶ {}", act.label)).color(Color32::from_rgb(235, 225, 160)));
            }
        });
        ui.separator();
        ui.horizontal(|ui| {
            for (t, name) in [
                (Tab::Identity, "Identity"),
                (Tab::Behavior, "Behavior"),
                (Tab::Mind, "Mind"),
                (Tab::Experiences, "Experiences"),
                (Tab::Thoughts, "Thoughts"),
            ] {
                ui.selectable_value(&mut view.tab, t, RichText::new(name).size(14.0));
            }
        });
        ui.separator();
        egui::ScrollArea::vertical().id_salt(("insp", view.tab as u8)).auto_shrink([false, false]).show(ui, |ui| match view.tab {
            Tab::Identity => {
                let bg = view.backgrounds.get(&c.id).cloned();
                let a = bg.as_ref().and_then(|b| background(ui, snap, b));
                if let Some(o) = identity(ui, conn, snap, &c).or(a) {
                    view.select(o, snap, true);
                }
            }
            Tab::Behavior => behavior(ui, conn, snap, &c),
            Tab::Mind => beliefs(ui, conn, view, snap, &c),
            Tab::Experiences => experiences(ui, conn, net, view, snap, &c),
            Tab::Thoughts => thoughts(ui, view, snap, &c),
        });
    });
}

fn technique_style(t: &str) -> (&'static str, Color32) {
    match t {
        "fire" => ("🔥", Color32::from_rgb(255, 140, 60)),
        "cooking" => ("🍖", Color32::from_rgb(230, 160, 110)),
        "spear" => ("🗡", Color32::from_rgb(190, 190, 210)),
        "shelter" => ("⛺", Color32::from_rgb(200, 150, 90)),
        "storage" => ("📦", Color32::from_rgb(200, 170, 110)),
        "cloak" => ("🧥", Color32::from_rgb(170, 130, 90)),
        "torch" => ("🕯", Color32::from_rgb(255, 200, 90)),
        "planting" => ("🌱", Color32::from_rgb(140, 210, 110)),
        "writing" => ("✍", Color32::from_rgb(230, 210, 170)),
        _ => ("•", Color32::from_rgb(170, 180, 200)),
    }
}

/// The selected character's fight: participants, their health and actions, what the
/// viewer saw (hits, blocks, dodges, misses) and what they said.
pub fn fight_panel(ctx: &egui::Context, view: &mut View, snap: &Snap) {
    let Some(sel) = view.selected else { return };
    let group = view.fight_group(sel);
    if group.is_empty() {
        return;
    }
    let area = ctx.available_rect();
    let mut go = None;
    egui::Window::new("⚔ Fight")
        .id(egui::Id::new("fight-panel"))
        .default_pos(area.left_top() + egui::vec2(12.0, 12.0))
        .default_width(300.0)
        .resizable(false)
        .collapsible(true)
        .show(ctx, |ui| {
            let mut total = crate::state::Tally::default();
            for id in &group {
                let t = view.tally.get(id).copied().unwrap_or_default();
                total.hits += t.hits;
                total.blocks += t.blocks;
                total.dodges += t.dodges;
                total.misses += t.misses;
                let Some(c) = snap.chars.get(id) else { continue };
                let col = if c.kind == "person" { view.community_color(*id) } else { WEAK };
                ui.horizontal(|ui| {
                    ui.label(RichText::new("■").color(col));
                    let name = RichText::new(snap.name(*id)).strong();
                    if ui.link(name).clicked() {
                        go = Some(*id);
                    }
                    if let Some(k) = view.community_of.get(id) {
                        ui.label(RichText::new(&view.communities[*k].name).small().color(col));
                    }
                });
                ui.horizontal(|ui| {
                    if let Some(v) = snap.vitals.get(id) {
                        let hp = need(v.hp, v.hp_rate, v.at_ms, snap.now, v.max_hp);
                        ui.add_sized(
                            [120.0, 12.0],
                            egui::ProgressBar::new((hp / v.max_hp.max(1.0)).clamp(0.0, 1.0)).fill(col).desired_height(10.0).text(RichText::new(format!("{hp:.0}/{:.0}", v.max_hp)).small()),
                        );
                    } else {
                        ui.label(RichText::new("down").color(Color32::from_rgb(230, 90, 80)));
                    }
                    let act = snap.activity.get(id).map(|a| a.label.clone()).unwrap_or_else(|| "—".into());
                    ui.label(RichText::new(act).small().color(Color32::from_rgb(235, 225, 160)));
                });
                ui.label(RichText::new(format!("hits {} · blocks {} · dodges {} · misses {}", t.hits, t.blocks, t.dodges, t.misses)).small().color(WEAK));
                ui.add_space(3.0);
            }
            ui.separator();
            ui.label(RichText::new(format!("seen: {} hits · {} blocked · {} dodged · {} missed", total.hits, total.blocks, total.dodges, total.misses)).strong());
            let said: Vec<&Chronicle> = view.chronicle.iter().filter(|r| r.kind == "speech" && group.contains(&r.a)).take(3).collect();
            if !said.is_empty() {
                ui.separator();
                for r in said {
                    ui.add(egui::Label::new(RichText::new(format!("{} {}", snap.stamp(r.at_ms), r.text)).small().italics()).wrap());
                }
            }
        });
    if let Some(id) = go {
        view.select(id, snap, true);
    }
}

/// Pinned sign text (opened by clicking a sign on the map).
pub fn sign_window(ctx: &egui::Context, view: &mut View, snap: &Snap) {
    let Some(sid) = view.open_sign else { return };
    let text = snap.artifacts.iter().find(|a| a.holder == crate::map::SIGN_BIT | sid);
    let mut open = true;
    egui::Window::new("Sign").id(egui::Id::new("sign-window")).open(&mut open).resizable(false).default_width(320.0).show(ctx, |ui| match text {
        Some(a) => {
            ui.add(egui::Label::new(RichText::new(&a.text).size(14.0).italics().color(Color32::from_rgb(236, 224, 196))).wrap());
            ui.add_space(4.0);
            ui.label(RichText::new(format!("— {} · {} · topic {}", a.author_name, snap.stamp(a.written_ms), if a.topic.is_empty() { "none" } else { &a.topic })).small().color(WEAK));
        }
        None => {
            ui.label(RichText::new("This sign is blank or gone.").color(WEAK));
        }
    });
    if !open {
        view.open_sign = None;
    }
}

/// Communities: members alive, home, and what their stores hold; click to jump there.
fn communities(ui: &mut egui::Ui, view: &mut View, net: &Net, snap: &Snap) {
    let Some(conn) = &net.conn else { return };
    if view.communities.is_empty() {
        ui.label(RichText::new("No communities yet.").color(WEAK));
        return;
    }
    let storages: Vec<&Structure> = snap.structures.iter().filter(|s| s.kind == "storage").collect();
    let mut stock: std::collections::HashMap<u64, Vec<(String, u32)>> = std::collections::HashMap::new();
    for i in conn.db.inventory().iter() {
        if i.owner >= crate::map::SIGN_BIT && i.qty > 0 {
            stock.entry(i.owner - crate::map::SIGN_BIT).or_default().push((i.item, i.qty));
        }
    }
    let mut jump = None;
    egui::ScrollArea::vertical().id_salt("communities").max_height(ui.available_height() * 0.42).auto_shrink([false, true]).show(ui, |ui| {
        for (k, com) in view.communities.iter().enumerate() {
            let alive = com.members.iter().filter(|m| snap.chars.get(m).is_some_and(|c| c.alive)).count();
            let mut totals: std::collections::BTreeMap<String, u32> = std::collections::BTreeMap::new();
            let mut n_stores = 0;
            for s in &storages {
                let near = (egui::pos2(s.x, s.y) - com.home).length() < 14.0;
                if near || com.members.contains(&s.owner) {
                    n_stores += 1;
                    for (item, q) in stock.get(&s.id).into_iter().flatten() {
                        *totals.entry(item.clone()).or_default() += q;
                    }
                }
            }
            let r = egui::Frame::new()
                .fill(Color32::from_rgb(28, 32, 40))
                .stroke(egui::Stroke::new(1.0, com.color.gamma_multiply(0.5)))
                .corner_radius(5.0)
                .inner_margin(egui::Margin::symmetric(8, 5))
                .show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    ui.horizontal(|ui| {
                        ui.label(RichText::new("■").color(com.color));
                        ui.label(RichText::new(&com.name).strong());
                        ui.label(RichText::new(com.kind).small().color(WEAK));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.label(RichText::new(format!("{alive}/{} alive", com.members.len())).small());
                        });
                    });
                    ui.label(RichText::new(format!("home ({:.0}, {:.0}) · {n_stores} store{}", com.home.x, com.home.y, if n_stores == 1 { "" } else { "s" })).small().color(WEAK));
                    if totals.is_empty() {
                        ui.label(RichText::new("stores empty").small().color(WEAK));
                    } else {
                        let line = totals.iter().map(|(i, q)| format!("{i} {q}")).collect::<Vec<_>>().join(" · ");
                        ui.add(egui::Label::new(RichText::new(line).small().color(Color32::from_rgb(230, 214, 170))).wrap());
                    }
                })
                .response
                .interact(egui::Sense::click())
                .on_hover_cursor(egui::CursorIcon::PointingHand);
            if r.clicked() {
                jump = Some(k);
            }
            ui.add_space(3.0);
        }
    });
    if let Some(k) = jump {
        view.follow = false;
        view.center = view.communities[k].home;
        view.zoom = view.zoom.max(12.0);
    }
    ui.separator();
}

/// Origin and household (towns) or band history, from the `background` row.
fn background(ui: &mut egui::Ui, snap: &Snap, b: &serde_json::Value) -> Option<u32> {
    let mut go = None;
    let s = |k: &str| b.get(k).and_then(|v| v.as_str()).unwrap_or("");
    section(ui, "Background");
    let mut people = |ui: &mut egui::Ui, label: &str, key: &str| {
        if let Some(list) = b.get(key).and_then(|v| v.as_array()).filter(|l| !l.is_empty()) {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(label).color(WEAK));
                for p in list {
                    let id = p.get("id").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                    let name = p.get("name").and_then(|v| v.as_str()).unwrap_or("?");
                    let occ = p.get("occupation").and_then(|v| v.as_str()).map(|o| format!(" ({o})")).unwrap_or_default();
                    if ui.link(RichText::new(format!("{name}{occ}")).color(person_color(id))).clicked() && id != 0 {
                        go = Some(id);
                    }
                }
            });
        }
    };
    match s("origin") {
        "town" => {
            ui.label(RichText::new(format!("{} of {}", if s("occupation").is_empty() { "townsperson" } else { s("occupation") }, s("town"))).strong());
            if !s("town_character").is_empty() {
                ui.add(egui::Label::new(RichText::new(s("town_character")).italics().small().color(Color32::from_rgb(210, 200, 180))).wrap());
            }
            people(ui, "household", "household");
        }
        "band" => {
            ui.label(RichText::new(format!("of {}", s("band"))).strong());
            if !s("history").is_empty() {
                ui.add(egui::Label::new(RichText::new(s("history")).italics().small().color(Color32::from_rgb(210, 200, 180))).wrap());
            }
            people(ui, "companions", "companions");
        }
        other => {
            ui.label(RichText::new(if other.is_empty() { "unknown origin" } else { other }).color(WEAK));
        }
    }
    let _ = snap;
    go
}

fn section(ui: &mut egui::Ui, title: &str) {
    ui.add_space(6.0);
    ui.label(RichText::new(title).strong().color(Color32::from_rgb(200, 210, 225)));
}

fn identity(ui: &mut egui::Ui, conn: &DbConnection, snap: &Snap, c: &Character) -> Option<u32> {
    let mut go = None;
    if let Some(p) = snap.personas.get(&c.id) {
        ui.add(egui::Label::new(RichText::new(&p.narrative).italics().size(14.0)).wrap());
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("mood").color(WEAK));
            ui.label(RichText::new(&p.mood).strong().color(Color32::from_rgb(240, 210, 150)));
            ui.label(RichText::new(format!("· persona v{} · {}", p.version, snap.stamp(p.updated_ms))).small().color(WEAK));
        });
        if !p.values.is_empty() {
            section(ui, "Values");
            ui.horizontal_wrapped(|ui| {
                for v in &p.values {
                    egui::Frame::new().fill(Color32::from_rgb(40, 52, 66)).corner_radius(10.0).inner_margin(egui::Margin::symmetric(8, 2)).show(ui, |ui| {
                        ui.add(egui::Label::new(v.as_str()).extend());
                    });
                }
            });
        }
        if !p.goals.is_empty() {
            section(ui, "Goals");
            for g in &p.goals {
                ui.label(format!("◆ {g}"));
            }
        }
        if let Ok(serde_json::Value::Object(traits)) = serde_json::from_str::<serde_json::Value>(&p.traits) {
            if !traits.is_empty() {
                section(ui, "Traits");
                for (k, v) in traits {
                    let v = v.as_f64().unwrap_or(0.0) as f32;
                    bar(ui, &k, v / 100.0, Color32::from_rgb(110, 120, 200), format!("{v:.0}"));
                }
            }
        }
    } else if c.kind == "person" {
        ui.label(RichText::new("No persona yet.").color(WEAK));
    }
    let mut know: Vec<KnowHow> = conn.db.know_how().iter().filter(|k| k.actor == c.id).collect();
    know.sort_by_key(|k| k.since_ms);
    if c.kind == "person" {
        section(ui, &format!("Know-how ({})", know.len()));
        if know.is_empty() {
            ui.label(RichText::new("no techniques yet").color(WEAK));
        }
        ui.horizontal_wrapped(|ui| {
            for k in &know {
                let (icon, col) = technique_style(&k.technique);
                egui::Frame::new().fill(col.gamma_multiply(0.28)).stroke(egui::Stroke::new(1.0, col.gamma_multiply(0.7))).corner_radius(10.0).inner_margin(egui::Margin::symmetric(8, 2)).show(ui, |ui| {
                    ui.add(egui::Label::new(RichText::new(format!("{icon} {}", k.technique)).color(Color32::WHITE)).extend());
                })
                .response
                .on_hover_text(format!("{} · since {}", k.source, snap.stamp(k.since_ms)));
            }
        });
    }
    let tablets: Vec<&Artifact> = snap.artifacts.iter().filter(|a| a.holder == c.id as u64).collect();
    if !tablets.is_empty() {
        section(ui, &format!("Carried writings ({})", tablets.len()));
        for a in tablets {
            egui::CollapsingHeader::new(RichText::new(format!("📜 {} — {} by {}", a.kind, if a.topic.is_empty() { "untitled" } else { &a.topic }, a.author_name)))
                .id_salt(("artifact", a.id))
                .show(ui, |ui| {
                    ui.add(egui::Label::new(RichText::new(&a.text).italics().color(Color32::from_rgb(232, 220, 190))).wrap());
                    ui.label(RichText::new(format!("written {}", snap.stamp(a.written_ms))).small().color(WEAK));
                });
        }
    }
    section(ui, "Vitals");
    if let Some(v) = snap.vitals.get(&c.id) {
        let hp = need(v.hp, v.hp_rate, v.at_ms, snap.now, v.max_hp);
        let hunger = need(v.hunger, v.hunger_rate, v.at_ms, snap.now, 100.0);
        let energy = need(v.energy, v.energy_rate, v.at_ms, snap.now, 100.0);
        bar(ui, "health", hp / v.max_hp.max(1.0), Color32::from_rgb(80, 180, 90), format!("{hp:.0} / {:.0}", v.max_hp));
        bar(ui, "hunger", hunger / 100.0, Color32::from_rgb(200, 130, 60), format!("{hunger:.0}  ({:+.1}/min)", v.hunger_rate));
        bar(ui, "energy", energy / 100.0, Color32::from_rgb(70, 140, 210), format!("{energy:.0}  ({:+.1}/min)", v.energy_rate));
        if v.hurt_ms > 0 {
            ui.label(RichText::new(format!("last hurt {} by {}", snap.stamp(v.hurt_ms), snap.name(v.hurt_by))).small().color(WEAK));
        }
    } else {
        ui.label(RichText::new("—").color(WEAK));
    }
    section(ui, "Inventory");
    let items: Vec<Inventory> = conn.db.inventory().iter().filter(|i| i.owner == c.id as u64 && i.qty > 0).collect();
    if items.is_empty() {
        ui.label(RichText::new("empty-handed").color(WEAK));
    } else {
        ui.horizontal_wrapped(|ui| {
            for i in items {
                egui::Frame::new().fill(Color32::from_rgb(52, 46, 36)).corner_radius(4.0).inner_margin(egui::Margin::symmetric(6, 2)).show(ui, |ui| {
                    ui.add(egui::Label::new(format!("{} × {}", i.item, i.qty)).extend());
                });
            }
        });
    }
    section(ui, "Life");
    ui.label(RichText::new(format!(
        "age {:.1} days · born {} · home ({:.0}, {:.0}) · {}",
        snap.age_days(c),
        snap.stamp(c.born_ms),
        c.home_x,
        c.home_y,
        if c.ai { "AI mind" } else { "instinct / human" }
    ))
    .small()
    .color(WEAK));
    let mut link = |ui: &mut egui::Ui, id: u32| {
        if ui.link(RichText::new(snap.name(id)).color(person_color(id))).clicked() {
            go = Some(id);
        }
    };
    if c.parent_a != 0 || c.parent_b != 0 {
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("parents").color(WEAK));
            for p in [c.parent_a, c.parent_b].into_iter().filter(|p| *p != 0) {
                link(ui, p);
            }
        });
    }
    let children: Vec<u32> = {
        let mut v: Vec<u32> = snap.chars.values().filter(|k| k.id != c.id && (k.parent_a == c.id || k.parent_b == c.id)).map(|k| k.id).collect();
        v.sort();
        v
    };
    if !children.is_empty() {
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("children").color(WEAK));
            for k in children {
                link(ui, k);
            }
        });
    }
    for e in snap.expecting.iter().filter(|e| e.a == c.id || e.b == c.id) {
        let partner = if e.a == c.id { e.b } else { e.a };
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("👶 expecting a child with").color(Color32::from_rgb(255, 170, 210)));
            link(ui, partner);
            ui.label(RichText::new(format!("· due {}", snap.stamp(e.due_ms))).small().color(WEAK));
        });
    }
    for b in snap.bond_offers.iter().filter(|b| b.from == c.id || b.to == c.id) {
        ui.horizontal_wrapped(|ui| {
            if b.from == c.id {
                ui.label(RichText::new("❤ offered a bond to").color(Color32::from_rgb(255, 160, 200)));
                link(ui, b.to);
            } else {
                ui.label(RichText::new("❤ was offered a bond by").color(Color32::from_rgb(255, 160, 200)));
                link(ui, b.from);
            }
            ui.label(RichText::new(snap.stamp(b.at_ms)).small().color(WEAK));
        });
    }
    go
}

fn behavior(ui: &mut egui::Ui, conn: &DbConnection, snap: &Snap, c: &Character) {
    let brain = conn.db.brain().id().find(&c.id);
    let state = conn.db.mind_state().id().find(&c.id);
    let Some(brain) = brain else {
        ui.label(RichText::new("No behavior installed.").color(WEAK));
        return;
    };
    if !brain.plan.is_empty() {
        section(ui, "Plan");
        ui.add(egui::Label::new(RichText::new(&brain.plan).size(14.0).color(Color32::from_rgb(235, 230, 200))).wrap());
    }
    ui.add_space(4.0);
    ui.label(
        RichText::new(format!("source {} · revision {} · installed {}", brain.source, brain.revision, snap.stamp(brain.installed_ms)))
            .small()
            .color(WEAK),
    );
    let active: Vec<u16> = state.as_ref().map(|s| s.active.clone()).unwrap_or_default();
    if let Some(s) = &state {
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new("status").color(WEAK));
            ui.label(RichText::new(&s.status).strong().color(Color32::from_rgb(255, 220, 110)));
            if s.fails > 0 {
                ui.label(RichText::new(format!("{} fails", s.fails)).color(Color32::from_rgb(240, 120, 90)));
            }
        });
        if let Some(l) = &s.last {
            let (mark, col) = if l.ok { ("✔", Color32::from_rgb(120, 210, 120)) } else { ("✘", Color32::from_rgb(240, 110, 90)) };
            ui.label(RichText::new(format!("{mark} last step: node {} {}", l.node, l.why)).small().color(col));
        }
        if s.deliberated_ms > 0 {
            ui.label(RichText::new(format!("last deliberation {}", snap.stamp(s.deliberated_ms))).small().color(WEAK));
        }
    }
    section(ui, "Behavior graph");
    match graph::parse(&brain.graph) {
        Ok(g) => {
            egui::Frame::new().fill(Color32::from_rgb(16, 19, 24)).corner_radius(4.0).inner_margin(egui::Margin::same(6)).show(ui, |ui| {
                ui.set_width(ui.available_width());
                let mut id = 0u16;
                outline(ui, &g.root, 0, &mut id, &active);
            });
        }
        Err(e) => {
            ui.label(RichText::new(format!("unparsed graph: {e}")).color(Color32::from_rgb(240, 110, 90)));
            ui.add(egui::Label::new(RichText::new(&brain.graph).monospace().small()).wrap());
        }
    }
}

fn outline(ui: &mut egui::Ui, n: &Node, depth: usize, id: &mut u16, active: &[u16]) {
    let me = *id;
    *id += 1;
    let on = active.contains(&me);
    let text = format!("{:>2} {}{}", me, "  ".repeat(depth), graph::describe(n));
    let col = match n {
        Node::First(_) | Node::Seq(_) => Color32::from_rgb(150, 180, 230),
        Node::If(_) => Color32::from_rgb(210, 170, 240),
        Node::Do(_) => Color32::from_rgb(200, 225, 200),
        Node::Say(_) => Color32::from_rgb(170, 210, 255),
        Node::Wait(_) => Color32::from_rgb(180, 180, 180),
        Node::Think(_) => Color32::from_rgb(240, 200, 140),
    };
    let mut rt = RichText::new(text).monospace().size(12.5);
    rt = if on { rt.background_color(Color32::from_rgb(86, 74, 20)).color(Color32::from_rgb(255, 235, 140)).strong() } else { rt.color(col) };
    ui.add(egui::Label::new(rt).wrap());
    match n {
        Node::First(c) | Node::Seq(c) => c.children.iter().for_each(|ch| outline(ui, ch, depth + 1, id, active)),
        Node::If(i) => {
            outline(ui, &i.then, depth + 1, id, active);
            if let Some(e) = &i.otherwise {
                ui.label(RichText::new(format!("   {}else", "  ".repeat(depth))).monospace().size(12.5).color(WEAK));
                outline(ui, e, depth + 1, id, active);
            }
        }
        _ => {}
    }
}

fn beliefs(ui: &mut egui::Ui, conn: &DbConnection, view: &mut View, snap: &Snap, c: &Character) {
    let mut bs: Vec<Belief> = conn.db.belief().iter().filter(|b| b.actor == c.id).collect();
    bs.sort_by(|a, b| b.confidence.total_cmp(&a.confidence));
    section(ui, &format!("Known facts ({})", bs.len()));
    ui.label(RichText::new("From the character's own mind graph (not ground truth).").small().color(WEAK));
    if bs.is_empty() {
        ui.label(RichText::new("none yet").color(WEAK));
    }
    for b in bs {
        egui::Frame::new().fill(Color32::from_rgb(30, 34, 42)).corner_radius(4.0).inner_margin(egui::Margin::symmetric(6, 4)).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.add(egui::Label::new(&b.text).wrap());
            ui.horizontal(|ui| {
                let (rect, _) = ui.allocate_exact_size(egui::vec2(90.0, 6.0), egui::Sense::hover());
                ui.painter().rect_filled(rect, 3.0, Color32::from_rgb(50, 54, 62));
                let f = b.confidence.clamp(0.0, 1.0);
                ui.painter().rect_filled(egui::Rect::from_min_size(rect.min, egui::vec2(rect.width() * f, rect.height())), 3.0, Color32::from_rgb(120, 170, 240));
                ui.label(RichText::new(format!("{:.0}%", f * 100.0)).small());
                if !b.about.is_empty() {
                    ui.label(RichText::new(format!("about {}", b.about)).small().color(WEAK));
                }
                ui.label(RichText::new(snap.stamp(b.updated_ms)).small().color(WEAK));
            });
        });
    }
    let mut js: Vec<Judgment> = conn.db.judgment().iter().filter(|j| j.actor == c.id).collect();
    js.sort_by(|a, b| a.key.cmp(&b.key));
    section(ui, &format!("Judgments ({})", js.len()));
    for j in js {
        ui.horizontal(|ui| {
            ui.label(RichText::new(&j.key).monospace().color(Color32::from_rgb(210, 190, 250)));
            ui.label(RichText::new(format!("= {:.2}", j.value)).strong());
        });
        if !j.why.is_empty() {
            ui.add(egui::Label::new(RichText::new(&j.why).small().color(WEAK)).wrap());
        }
    }
    let places: Vec<Place> = conn.db.place().iter().filter(|p| p.actor == c.id).collect();
    section(ui, &format!("Places ({})", places.len()));
    for p in places {
        if ui.link(format!("⚑ {} ({:.0}, {:.0})", p.name, p.x, p.y)).clicked() {
            view.follow = false;
            view.center = egui::pos2(p.x, p.y);
        }
    }
    let mut rs: Vec<Relation> = conn.db.relation().iter().filter(|r| r.actor == c.id).collect();
    rs.sort_by(|a, b| (b.trust + b.affinity).total_cmp(&(a.trust + a.affinity)));
    section(ui, &format!("Relations ({})", rs.len()));
    let mut go = None;
    for r in rs {
        egui::Frame::new().fill(Color32::from_rgb(30, 34, 42)).corner_radius(4.0).inner_margin(egui::Margin::symmetric(6, 4)).show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.horizontal(|ui| {
                ui.label(RichText::new("●").color(person_color(r.other)));
                if ui.link(RichText::new(snap.name(r.other)).strong()).clicked() {
                    go = Some(r.other);
                }
                ui.label(RichText::new(&r.label).color(Color32::from_rgb(240, 210, 150)));
            });
            signed_bar(ui, "trust", r.trust, 100.0);
            signed_bar(ui, "affinity", r.affinity, 100.0);
            if !r.note.is_empty() {
                ui.add(egui::Label::new(RichText::new(&r.note).small().italics().color(WEAK)).wrap());
            }
        });
    }
    if let Some(o) = go {
        view.select(o, snap, true);
    }
}

fn experience_style(kind: &str) -> (&'static str, Color32) {
    match kind {
        "saw" => ("👁", Color32::from_rgb(170, 200, 230)),
        "speech" | "heard" => ("💬", Color32::from_rgb(170, 205, 255)),
        "own" => ("✋", Color32::from_rgb(200, 200, 190)),
        "attacked" | "hurt" => ("⚔", Color32::from_rgb(255, 130, 110)),
        "gift" => ("🎁", Color32::from_rgb(230, 200, 255)),
        "family" => ("❤", Color32::from_rgb(255, 160, 200)),
        "birth" => ("👶", Color32::from_rgb(160, 240, 200)),
        "body" => ("♥", Color32::from_rgb(240, 180, 120)),
        "death" | "died" => ("☠", Color32::from_rgb(255, 110, 100)),
        _ => ("•", Color32::from_rgb(210, 210, 210)),
    }
}

fn experiences(ui: &mut egui::Ui, conn: &DbConnection, net: &Net, view: &mut View, snap: &Snap, c: &Character) {
    if !net.experiences_ready(c.id) {
        ui.label(RichText::new("Loading this character's experiences…").color(WEAK));
        return;
    }
    let upto = conn.db.mind_cursor().actor().find(&c.id).map(|m| m.upto);
    let mut rows: Vec<Experience> = conn.db.experience().iter().filter(|e| e.observer == c.id).collect();
    rows.sort_by(|a, b| b.id.cmp(&a.id));
    let pending = rows.iter().filter(|e| upto.map_or(true, |u| e.id > u)).count();
    section(ui, &format!("Experiences ({})", rows.len()));
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new("Everything that reached this character's senses.").small().color(WEAK));
        match upto {
            Some(u) => ui.label(RichText::new(format!("Mind integrated up to #{u}; {pending} not yet integrated.")).small().color(WEAK)),
            None => ui.label(RichText::new("The mind has not integrated anything yet.").small().color(WEAK)),
        };
    });
    if let Some(h) = view.exp_highlight {
        if !rows.iter().any(|e| e.id == h) {
            ui.label(RichText::new(format!("Experience #{h} is no longer in the retained window.")).small().color(Color32::from_rgb(240, 170, 90)));
        }
    }
    for e in &rows {
        let (icon, col) = experience_style(&e.kind);
        let fresh = upto.map_or(true, |u| e.id > u);
        let hl = view.exp_highlight == Some(e.id);
        let fill = if hl { Color32::from_rgb(70, 60, 20) } else { Color32::from_rgb(28, 32, 40) };
        let r = egui::Frame::new()
            .fill(fill)
            .stroke(if hl { egui::Stroke::new(1.5, Color32::from_rgb(255, 220, 110)) } else { egui::Stroke::NONE })
            .corner_radius(4.0)
            .inner_margin(egui::Margin::symmetric(6, 3))
            .show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.horizontal(|ui| {
                    ui.label(RichText::new(icon).color(col));
                    ui.label(RichText::new(&e.kind).small().strong().color(col));
                    ui.label(RichText::new(snap.stamp(e.at_ms)).small().color(WEAK));
                    ui.label(RichText::new(format!("#{}", e.id)).monospace().size(10.5).color(WEAK));
                    if fresh {
                        ui.label(RichText::new("● not yet integrated").small().color(Color32::from_rgb(255, 190, 90)))
                            .on_hover_text("id is above the mind cursor: the mind has not consolidated this yet");
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let (rect, _) = ui.allocate_exact_size(egui::vec2(50.0, 6.0), egui::Sense::hover());
                        let f = e.salience.clamp(0.0, 1.0);
                        ui.painter().rect_filled(rect, 3.0, Color32::from_rgb(50, 54, 62));
                        ui.painter().rect_filled(egui::Rect::from_min_size(rect.min, egui::vec2(rect.width() * f, rect.height())), 3.0, Color32::from_rgb(240, 180, 90));
                    })
                    .response
                    .on_hover_text(format!("salience {:.2}", e.salience));
                });
                ui.add(egui::Label::new(RichText::new(&e.text).color(Color32::from_rgb(225, 225, 225))).wrap());
            })
            .response;
        if hl && view.exp_scroll {
            r.scroll_to_me(Some(egui::Align::Center));
            view.exp_scroll = false;
        }
    }
    if rows.is_empty() {
        ui.label(RichText::new("Nothing perceived yet.").color(WEAK));
    }
}

fn thoughts(ui: &mut egui::Ui, view: &mut View, snap: &Snap, c: &Character) {
    let Some(ts) = view.thoughts.get(&c.id) else {
        ui.label(RichText::new("No model thoughts recorded.").color(WEAK));
        return;
    };
    let mut jump = None;
    section(ui, &format!("Thoughts ({})", ts.len()));
    for t in ts.iter().take(100) {
        let col = match t.kind.as_str() {
            "deliberate" => Color32::from_rgb(120, 180, 255),
            "consolidate" => Color32::from_rgb(180, 140, 250),
            "error" => Color32::from_rgb(250, 110, 90),
            _ => Color32::GRAY,
        };
        egui::Frame::new()
            .fill(Color32::from_rgb(28, 32, 40))
            .stroke(egui::Stroke::new(1.0, col.gamma_multiply(0.4)))
            .corner_radius(5.0)
            .inner_margin(egui::Margin::symmetric(8, 6))
            .show(ui, |ui| {
                ui.set_width(ui.available_width());
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new(&t.kind).strong().color(col));
                    ui.label(RichText::new(snap.stamp(t.at_ms)).small().color(WEAK));
                    ui.label(RichText::new(&t.model).small().color(Color32::from_rgb(200, 200, 160)));
                    ui.label(RichText::new(format!("{:.1}s · {} tok", t.latency_ms as f32 / 1000.0, t.tokens)).small().color(WEAK));
                });
                ui.add(egui::Label::new(RichText::new(&t.summary).color(Color32::from_rgb(225, 225, 225))).wrap());
                if !t.reference.is_empty() {
                    ui.label(RichText::new(format!("ref {}", t.reference)).monospace().size(10.5).color(WEAK))
                        .on_hover_text("reasoning id; mind-graph edges carry it as `thought`");
                }
                if let Some(ids) = view.thought_exps.get(&t.id).filter(|v| !v.is_empty()) {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new("integrated").small().color(WEAK));
                        for id in ids {
                            if ui.link(RichText::new(format!("#{id}")).monospace().size(11.0)).on_hover_text("show in Experiences").clicked() {
                                jump = Some(*id);
                            }
                        }
                    });
                }
                if !t.detail.is_empty() {
                    egui::CollapsingHeader::new(RichText::new("raw exchange").small()).id_salt(("thought", t.id)).show(ui, |ui| {
                        let pretty = serde_json::from_str::<serde_json::Value>(&t.detail)
                            .ok()
                            .and_then(|v| serde_json::to_string_pretty(&v).ok())
                            .unwrap_or_else(|| t.detail.clone());
                        egui::ScrollArea::both().id_salt(("detail", t.id)).max_height(360.0).show(ui, |ui| {
                            ui.add(egui::Label::new(RichText::new(pretty).monospace().size(11.5)).extend());
                        });
                    });
                }
            });
        ui.add_space(3.0);
    }
    if let Some(id) = jump {
        view.exp_highlight = Some(id);
        view.exp_scroll = true;
        view.tab = Tab::Experiences;
    }
}
