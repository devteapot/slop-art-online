//! Interface D's prompts, only while they matter: the F prompt beside what F would act on, and
//! the first-time tip ("New here").
//!
//! - **The F prompt** sits beside the person or thing F acts on: "F Talk · hold F · more" on a
//!   peaceful person (a tap of F talks, a hold lists every act), else the act a tap would do, or
//!   "Acts" when only the list has something. It hides while typing, while a list is open and
//!   on the death screen.
//! - **The tip** shows once a session on arrival (Settings › Play can turn tips off, or show them
//!   again): how to talk, and (since the cluster's weapon slot) that a sheathed weapon never
//!   strikes. "Got it" closes it; "All tips" opens Settings. It hides while a window holds the
//!   left anchor.

use super::hit::{Block, Hot, Tag, UiPointer};
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

/// The weapon's line of the tip shows once sheathe and draw is built (step 4).
pub const SHEATHE: bool = false;

/// Whether the first-time tip shows, and when it was dismissed.
#[derive(Resource, Default)]
pub struct Tip {
    pub shown: bool,
    pub dismissed: bool,
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
            Node { position_type: PositionType::Absolute, flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(7.0), Val::Px(12.0), Val::Px(6.0), Val::Px(6.0)), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(10.0)), display: Display::None, ..default() },
            BackgroundColor(wood::PARCH),
            BorderColor::all(wood::INK),
            wood::hard_shadow(3.0, 0.45),
            GlobalZIndex(15),
            Pickable::IGNORE,
        ))
        .with_children(|p| {
            wood::chip(p, f, "F", PromptKey);
            p.spawn((PromptLabel, Text::new(""), wood::ink(f, 15.0, 800), Pickable::IGNORE));
            p.spawn((PromptMore, Text::new(""), f.body(12.0, 700), TextColor(wood::MUTED), Node { padding: UiRect::left(Val::Px(8.0)), border: UiRect::left(Val::Px(2.0)), ..default() }, BorderColor::all(wood::DASH), Pickable::IGNORE));
        });
    // The first-time tip, bottom left.
    commands
        .spawn((
            HudRoot,
            TipCard,
            Block,
            Node { position_type: PositionType::Absolute, left: Val::Px(26.0), bottom: Val::Px(130.0), width: Val::Px(376.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(14.0), Val::Px(14.0), Val::Px(12.0), Val::Px(14.0)), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(12.0)), display: Display::None, ..default() },
            wood::wood(),
            GlobalZIndex(25),
        ))
        .with_children(|c| {
            c.spawn(wood::rim(9.0));
            c.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), ..default() }, Pickable::IGNORE)).with_children(|h| {
                h.spawn(wood::icon(&icons, Glyph::Ui(Mark::Talk), 18.0, wood::BRASS2));
                h.spawn((Text::new("New here"), wood::title(f, 18.0), Pickable::IGNORE));
            });
            rich(c, f, "Point at someone and press {F} to talk to them. {Enter} talks to whoever you point at, or to the room.", wood::PARCH);
            c.spawn((TipWeapon, Node { display: if SHEATHE { Display::Flex } else { Display::None }, ..default() }, Pickable::IGNORE)).with_children(|w| rich(w, f, "Your weapon is sheathed: a tap never strikes. {X} draws it, and it draws itself if you're attacked.", wood::PARCH));
            c.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(10.0), margin: UiRect::top(Val::Px(4.0)), ..default() }, Pickable::IGNORE)).with_children(|b| {
                kit::button(b, f, "Got it", "tip:ok", false);
                kit::button(b, f, "All tips", "tip:all", true);
            });
        });
}

/// The tip's buttons, and showing it once on arrival.
#[allow(clippy::too_many_arguments)]
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, mut tip: ResMut<Tip>, mut ws: ResMut<Windows>, prefs: Res<crate::keys::Prefs>, net: NonSend<crate::net::Net>, scene: NonSend<crate::world::Scene>, loading: Option<Res<crate::loading::Loading>>, mut page: ResMut<super::settings::Page>) {
    match kit::clicked(&ui, &tags) {
        Some("tip:ok") => tip.dismissed = true,
        Some("tip:all") => {
            tip.dismissed = true;
            *page = super::settings::Page::Play;
            ws.open(Win::Settings);
        }
        _ => {}
    }
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
    mut prompt: Query<&mut Node, (With<Prompt>, Without<TipCard>)>,
    mut key: Query<&mut Text, (With<PromptKey>, Without<PromptLabel>, Without<PromptMore>)>,
    mut label: Query<&mut Text, (With<PromptLabel>, Without<PromptKey>, Without<PromptMore>)>,
    mut more: Query<(&mut Text, &mut Node), (With<PromptMore>, Without<PromptKey>, Without<PromptLabel>, Without<Prompt>, Without<TipCard>)>,
    mut card: Query<&mut Node, (With<TipCard>, Without<Prompt>, Without<PromptMore>)>,
) {
    let f = binds.first(Act::Interact);
    // What F acts on, and what a tap does.
    let aimed = verbs.aim.as_ref().filter(|_| !input.chat_open && verbs.menu.is_none() && model.death.is_none());
    let person = aimed.and_then(|a| match a {
        crate::verbs::Aim::Creature { id } => model.actors.iter().find(|x| x.id == *id as u64),
        _ => None,
    });
    let peaceful_person = person.filter(|a| a.stance == super::model::Stance::Neutral && a.kind_person);
    let (text, more_text) = match (aimed, peaceful_person) {
        (Some(_), Some(_)) => ("Talk".to_string(), format!("hold {f} · more")),
        (Some(_), None) => match &verbs.likely {
            Some(c) => (super::label(&wood::readable(&c.label)), if verbs.has_options { format!("hold {f} · more") } else { String::new() }),
            None if verbs.has_options => (format!("{} · acts", super::label(&verbs.aim_name)), String::new()),
            None => (String::new(), String::new()),
        },
        _ => (String::new(), String::new()),
    };
    // Beside their head, else beside the cursor.
    let at = person.and_then(|a| cams.iter().find_map(|(c, t)| c.world_to_viewport(t, a.head).ok())).map(|p| p + Vec2::new(26.0, 6.0)).or_else(|| ui.pos.map(|p| p + Vec2::new(26.0, 10.0)));
    let on = !text.is_empty() && at.is_some() && !ui.over_ui;
    for mut n in &mut prompt {
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
