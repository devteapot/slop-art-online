//! Interface D's prompts, only while they matter: the F prompt beside what F would act on, and
//! the first-time tip ("New here").
//!
//! - **The F prompt** sits beside the person or thing F acts on: "F Talk · hold F · more" on a
//!   peaceful person (a tap of F talks, a hold lists every act), else the act a tap would do, or
//!   "Acts" when only the list has something. It hides while typing, while a list is open and
//!   on the death screen. It never covers a note: beside the head on the right, else on the
//!   left, else hidden while the note shows (the note wins; the prompt returns after).
//! - **The tip** shows once a session on arrival (Settings › Play can turn tips off, or show them
//!   again): how to talk, and (since the cluster's weapon slot) that a sheathed weapon never
//!   strikes. "Got it" closes it; "All tips" opens Settings. It hides while a window holds the
//!   left anchor.

use super::hit::{Block, Tag, UiPointer};
use super::icons::{Glyph, Icons, Mark};
use super::kit;
use super::model::HudModel;
use super::theme::Fonts;
use super::win::{Anchor, Win, Windows};
use super::{set_text, show, wood, HudRoot};
use crate::keys::{Act, Binds};
use bevy::prelude::*;
use bevy::ui::GlobalZIndex;

#[derive(Component)]
pub struct Prompt;
#[derive(Component)]
pub struct PromptKey;
#[derive(Component)]
pub struct PromptLabel;
#[derive(Component)]
pub struct PromptMore;
#[derive(Component)]
pub struct TipCard;
#[derive(Component)]
pub struct TipWeapon;

/// The least gap between the F prompt and a note (UI px).
const NOTE_GAP: f32 = 8.0;

/// The weapon's line of the tip shows once sheathe and draw is built (step 4).
pub const SHEATHE: bool = true;

/// Whether the first-time tip shows, and when it was dismissed.
#[derive(Resource, Default)]
pub struct Tip {
    pub shown: bool,
    pub dismissed: bool,
    /// Lists of acts opened toward someone (the prompt's "hold F · more" stops after two).
    pub holds: u32,
    was_open: bool,
}

/// Lay out words and key chips: `{F}` is a chip, anything else words that wrap.
pub fn rich(p: &mut ChildSpawnerCommands, f: &Fonts, text: &str, colour: Color) {
    p.spawn((Node { flex_direction: FlexDirection::Row, flex_wrap: FlexWrap::Wrap, align_items: AlignItems::Center, column_gap: Val::Px(4.0), row_gap: Val::Px(3.0), ..default() }, Pickable::IGNORE)).with_children(|r| {
        for w in text.split(' ').filter(|w| !w.is_empty()) {
            match w.strip_prefix('{').and_then(|w| w.split_once('}')) {
                Some((k, rest)) => {
                    wood::chip(r, f, k, ());
                    if !rest.is_empty() {
                        r.spawn((Text::new(rest), f.body(14.0, 600), TextColor(colour), Pickable::IGNORE));
                    }
                }
                None => {
                    r.spawn((Text::new(w), f.body(14.0, 600), TextColor(colour), Pickable::IGNORE));
                }
            }
        }
    });
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = &*fonts;
    commands
        .spawn((
            HudRoot,
            Prompt,
            Node { position_type: PositionType::Absolute, flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(7.0), Val::Px(12.0), Val::Px(6.0), Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(10.0), display: Display::None, ..default() },
            BackgroundColor(wood::surface()),
            BorderColor::all(wood::edge()),
            wood::hard_shadow(3.0, 0.45),
            GlobalZIndex(15),
            Pickable::IGNORE,
        ))
        .with_children(|p| {
            wood::chip(p, f, "F", PromptKey);
            p.spawn((PromptLabel, Text::new(""), wood::ink(f, 15.0, 800), Pickable::IGNORE));
            p.spawn((PromptMore, Text::new(""), f.body(12.0, 700), TextColor(wood::muted()), Node { padding: UiRect::left(Val::Px(8.0)), border: UiRect::left(Val::Px(2.0)), ..default() }, BorderColor::all(wood::line()), Pickable::IGNORE));
        });
    // The first-time tip, bottom left.
    commands
        .spawn((
            HudRoot,
            TipCard,
            Block,
            Node { position_type: PositionType::Absolute, left: Val::Px(26.0), bottom: Val::Px(130.0), width: Val::Px(376.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(14.0), Val::Px(14.0), Val::Px(12.0), Val::Px(14.0)), border: wood::b(3.0), border_radius: wood::r(12.0), display: Display::None, ..default() },
            wood::wood(),
            GlobalZIndex(25),
        ))
        .with_children(|c| {
            c.spawn(wood::rim(9.0));
            c.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), ..default() }, Pickable::IGNORE)).with_children(|h| {
                h.spawn(wood::icon(&icons, Glyph::Ui(Mark::Talk), 18.0, wood::t().title));
                h.spawn((Text::new("New here"), wood::title(f, 18.0), Pickable::IGNORE));
            });
            rich(c, f, "Point at someone and press {F} to talk to them. {Enter} talks to whoever you point at, or to the room.", wood::on_panel());
            c.spawn((TipWeapon, Node { display: if SHEATHE { Display::Flex } else { Display::None }, ..default() }, Pickable::IGNORE)).with_children(|w| rich(w, f, "Your weapon is sheathed: a tap never strikes. {X} draws it, and it draws itself if you're attacked.", wood::on_panel()));
            c.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(10.0), margin: UiRect::top(Val::Px(4.0)), ..default() }, Pickable::IGNORE)).with_children(|b| {
                kit::button(b, f, "Got it", "tip:ok", false);
                kit::button(b, f, "All tips", "tip:all", true);
            });
        });
}

/// The tip's buttons, and showing it once on arrival.
#[allow(clippy::too_many_arguments)]
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, mut tip: ResMut<Tip>, mut ws: ResMut<Windows>, verbs: Res<crate::verbs::Verbs>, prefs: Res<crate::keys::Prefs>, net: NonSend<crate::net::Net>, scene: NonSend<crate::world::Scene>, loading: Option<Res<crate::loading::Loading>>, mut page: ResMut<super::settings::Page>) {
    match kit::clicked(&ui, &tags) {
        Some("tip:ok") => tip.dismissed = true,
        Some("tip:all") => {
            tip.dismissed = true;
            *page = super::settings::Page::Play;
            ws.open(Win::Settings);
        }
        _ => {}
    }
    let open = verbs.menu.as_ref().is_some_and(|m| m.person);
    if open && !tip.was_open {
        tip.holds += 1;
    }
    tip.was_open = open;
    let arrived = net.my_id.is_some_and(|id| scene.shown.contains_key(&id)) && crate::loading::Loading::clear(loading.as_deref());
    if arrived && !tip.shown && prefs.tips {
        tip.shown = true;
        info!("ui: first-time tip shown");
    }
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    verbs: Res<crate::verbs::Verbs>,
    input: Res<crate::controls::Input>,
    binds: Res<Binds>,
    ws: Res<Windows>,
    tip: Res<Tip>,
    prefs: Res<crate::keys::Prefs>,
    ui: Res<UiPointer>,
    cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>,
    mut prompt: Query<(&mut Node, &ComputedNode), (With<Prompt>, Without<TipCard>, Without<super::verbs::ToastRow>)>,
    mut key: Query<&mut Text, (With<PromptKey>, Without<PromptLabel>, Without<PromptMore>)>,
    mut label: Query<&mut Text, (With<PromptLabel>, Without<PromptKey>, Without<PromptMore>)>,
    mut more: Query<(&mut Text, &mut Node), (With<PromptMore>, Without<PromptKey>, Without<PromptLabel>, Without<Prompt>, Without<TipCard>, Without<super::verbs::ToastRow>)>,
    mut card: Query<&mut Node, (With<TipCard>, Without<Prompt>, Without<PromptMore>, Without<super::verbs::ToastRow>)>,
    notes: Query<(&Node, &ComputedNode, &bevy::ui::UiGlobalTransform), (With<super::verbs::ToastRow>, Without<Prompt>, Without<PromptMore>, Without<TipCard>)>,
    mut last_size: Local<Vec2>,
) {
    let f = binds.first(Act::Interact);
    // What F acts on, and what a tap does.
    let aimed = verbs.aim.as_ref().filter(|_| !input.chat_open && verbs.menu.is_none() && verbs.wheel.is_none() && model.death.is_none());
    let person = aimed.and_then(|a| match a {
        crate::verbs::Aim::Creature { id } => model.actors.iter().find(|x| x.id == *id as u64),
        _ => None,
    });
    let peaceful_person = person.filter(|a| a.stance == super::model::Stance::Neutral && a.kind_person);
    // "hold F · more" until the list has been opened with a hold a few times (always in a
    // dense theme).
    let more_hint = |s: String| if wood::t().help || tip.holds < 2 { s } else { String::new() };
    let (text, more_text) = match (aimed, peaceful_person) {
        (Some(_), Some(_)) => ("Talk".to_string(), more_hint(format!("hold {f} · more"))),
        (Some(_), None) => match &verbs.likely {
            Some(c) => (super::label(&wood::readable(&c.label)), if verbs.has_options { more_hint(format!("hold {f} · more")) } else { String::new() }),
            None if verbs.has_options => (format!("{} · acts", super::label(&verbs.aim_name)), String::new()),
            None => (String::new(), String::new()),
        },
        _ => (String::new(), String::new()),
    };
    // Beside their head (else beside the cursor), right of it, or left when a note is in the
    // way: the prompt never covers a note (notes keep their lane above the bar). With neither
    // side clear the note wins for its few seconds, and the prompt returns after.
    let px = ui.scale.max(0.01);
    let lane: Vec<Rect> = notes.iter().filter(|(n, c, _)| n.display != Display::None && c.size().x > 0.0).map(|(_, c, t)| Rect::from_center_size(t.affine().translation / px, c.size() / px).inflate(NOTE_GAP)).collect();
    // Its size as last drawn (a hidden node measures nothing; a guess could flicker beside a note).
    if let Some(z) = prompt.iter().map(|(_, c)| c.size() / px).find(|z| z.x > 0.0) {
        *last_size = z;
    }
    let size = if last_size.x > 0.0 { *last_size } else { Vec2::new(200.0, 34.0) };
    let clear = |p: &Vec2| lane.iter().all(|r| r.intersect(Rect::from_corners(*p, *p + size)).is_empty());
    let beside = person.and_then(|a| cams.iter().find_map(|(c, t)| c.world_to_viewport(t, a.head).ok())).map(|p| (p, 6.0)).or_else(|| ui.pos.map(|p| (p, 10.0)));
    let at = beside.and_then(|(p, dy)| [p + Vec2::new(26.0, dy), p + Vec2::new(-26.0 - size.x, dy)].into_iter().find(clear));
    let on = !text.is_empty() && at.is_some() && !ui.over_ui;
    for (mut n, _) in &mut prompt {
        show(&mut n, on);
        if let Some(p) = at.filter(|_| on) {
            let v = ui.val(p);
            let (l, t) = (Val::Px(v.x.round()), Val::Px(v.y.round()));
            if n.left != l {
                n.left = l;
            }
            if n.top != t {
                n.top = t;
            }
        }
    }
    for mut t in &mut key {
        set_text(&mut t, &f);
    }
    for mut t in &mut label {
        set_text(&mut t, &text);
    }
    for (mut t, mut n) in &mut more {
        show(&mut n, !more_text.is_empty());
        set_text(&mut t, &more_text);
    }
    let left_taken = ws.at(Anchor::Left).is_some() || ws.top().is_some_and(|w| w.wide());
    for mut n in &mut card {
        show(&mut n, tip.shown && !tip.dismissed && prefs.tips && !left_taken && model.death.is_none());
    }
}
