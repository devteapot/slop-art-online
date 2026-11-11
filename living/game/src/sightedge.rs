//! How the edge of my character's sight is shown (docs/GAME_BRIEF.md, "Edge of sight").
//! Presentation only: the authority decides whom I perceive; this only draws where that ends.
//!
//! - **Not seen now** (the default since sight-2): ground, buildings and scenery my character
//!   does not see now are drawn dimmer and flatter (less saturation and contrast): beyond my
//!   sight, with a soft band of a few metres, and behind what blocks my sight lines (walls,
//!   buildings, stalls, rock, shut gates), with a soft edge of about half a tile (`sightfield.rs`).
//!   They are public and stay drawn; this marks them as outside sight. People whose sight line
//!   breaks fade out as it breaks.
//! - **Fade:** people fade in and out at the edge of sight (`fade.rs`); nothing else changes.
//! - **Limited view:** as "not seen now" for people, and the view fogs from my sight radius to
//!   1.3 × of it, in the fog's (sky) colour, and stops drawing past that (the camera's far
//!   plane); what lies behind something within it fogs most of the way. So the screen shows
//!   about what my character sees. The camera's angle and distance are unchanged.
//!
//! The marks are worked out per pixel in the finishing pass (`edges.wesl`: the world position of
//! each pixel from depth): the radius on the ground plane, and the sight field sampled there.
//! The fog is round my character rather than the camera's distance fog, because the eye sits
//! about 22 m from me: a camera fog at a 14 m night sight would hide my own character.
//!
//! The radius comes from the world's rules: the installed skill script (`verbs.rs` compiles it)
//! answers `senses(a)` for my character, with night from the displayed clock and my torch from
//! my inventory, the same law the authority's sweep asks. It eases over about a second when day
//! turns to night or a torch is lit.
//!
//! F2 cycles the modes, with a note naming the new one and the key. The same note shows once on
//! arrival, so the key can be found. `LIVING_SIGHT_EDGE=fade|unseen|limited` sets the starting
//! mode (headless captures).

use crate::net::Net;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::script::{ActorFacts, SkillCtx};
use spacetimedb_sdk::Table;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Mode {
    Fade,
    #[default]
    Unseen,
    Limited,
}

impl Mode {
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "fade" => Some(Mode::Fade),
            "unseen" | "not-seen" | "notseen" => Some(Mode::Unseen),
            "limited" => Some(Mode::Limited),
            _ => None,
        }
    }

    fn next(self) -> Self {
        match self {
            Mode::Unseen => Mode::Limited,
            Mode::Limited => Mode::Fade,
            Mode::Fade => Mode::Unseen,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Mode::Fade => "Edge of sight: fade",
            Mode::Unseen => "Edge of sight: not seen now",
            Mode::Limited => "Edge of sight: limited view",
        }
    }

    /// The note naming the mode and the key that changes it.
    pub fn note(self) -> String {
        format!("{}  ·  F2 changes how it is shown", self.label())
    }

    /// The finishing pass's code for it.
    fn code(self) -> f32 {
        match self {
            Mode::Fade => 0.0,
            Mode::Unseen => 1.0,
            Mode::Limited => 2.0,
        }
    }
}

/// Where the fully fogged view ends, as a multiple of the sight radius (Limited view).
pub const LIMIT: f32 = 1.3;
/// The soft band of "not seen now" (m): from 1.5 m inside the radius to this much beyond it.
const BAND_IN: f32 = 1.5;
const BAND_OUT: f32 = 3.0;
/// How strongly ground beyond sight is marked: less saturated, flattened this far toward the
/// fog's colour (which follows the light, so night stays dark), dimmer, a little cooler.
const DESATURATE: f32 = 0.7;
const FLATTEN: f32 = 0.35;
const DIM: f32 = 0.25;
/// The radius eases toward the rules' answer at this rate (1/s): about a second.
const EASE: f32 = 3.0;
/// The law is asked this often (s); its answer is memoised per state by the script anyway.
const ASK_S: f32 = 0.25;
/// Beyond the fully fogged radius, drawing stops this much further on (m).
const FAR_MARGIN: f32 = 10.0;
/// Limited view: how far toward the fog what lies behind something within sight goes.
const SHADOW_FOG: f32 = 0.8;
/// The arrival note stays this much longer than other notes (s).
const NOTE_EXTRA_S: f64 = 3.0;

#[derive(Resource)]
pub struct SightEdge {
    pub mode: Mode,
    /// The radius shown (m), eased.
    pub radius: f32,
    /// The rules' answer for me now (m), once known.
    pub want: Option<f32>,
    next_ask: f32,
    next_report: f32,
    /// The camera's far plane before Limited view brought it in.
    far: Option<f32>,
    /// The arrival note has been shown.
    noted: bool,
}

impl Default for SightEdge {
    fn default() -> Self {
        let mode = std::env::var("LIVING_SIGHT_EDGE").ok().and_then(|v| Mode::parse(&v)).unwrap_or_default();
        Self { mode, radius: 11.0, want: None, next_ask: 0.0, next_report: 0.0, far: None, noted: false }
    }
}

impl SightEdge {
    /// In limited view, outlines are drawn only within this ground distance of me (half way into
    /// the fog band), since the finishing pass's fog does not cover them: where I stand and the
    /// distance.
    pub fn outline_limit(&self, me: Option<Vec3>) -> Option<(Vec2, f32)> {
        let me = me.filter(|_| self.mode == Mode::Limited && self.want.is_some())?;
        Some((Vec2::new(me.x, me.z), self.radius * (1.0 + (LIMIT - 1.0) * 0.5)))
    }
}

pub struct SightEdgePlugin;

impl Plugin for SightEdgePlugin {
    fn build(&self, app: &mut App) {
        let edge = SightEdge::default();
        info!("sight edge: starting in {:?}", edge.mode);
        app.insert_resource(edge)
            .add_systems(Update, (update, far).chain().in_set(crate::phase::Phase::Camera).after(crate::camera::follow))
            .add_systems(PostUpdate, shade.after(crate::post::update));
    }
}

/// My sight now by the world's rules (`senses(a)`), or none before the script and my character
/// are known.
fn my_sight(net: &Net, rules: &crate::verbs::Rules, hour: f32) -> Option<f32> {
    let (conn, me, sc) = (net.conn.as_ref()?, net.my_id?, rules.scripts.as_ref()?);
    let c = conn.db.my_characters().id().find(&me)?;
    let mut inv: Vec<(String, u32)> = Vec::new();
    for r in conn.db.my_inventory().iter().filter(|r| r.owner == me as u64 && r.qty > 0) {
        match inv.iter_mut().find(|(k, _)| *k == r.item) {
            Some((_, n)) => *n += r.qty,
            None => inv.push((r.item, r.qty)),
        }
    }
    let night = living_rules::is_night(hour);
    let actor = ActorFacts { id: me, kind: c.kind.clone(), inv, ..Default::default() };
    let ctx = SkillCtx { actor, night, hour, ..Default::default() };
    match sc.senses(&ctx) {
        Ok(s) => Some(s.sight),
        Err(e) => {
            warn!("sight edge: the rules' senses law failed: {e}");
            None
        }
    }
}

/// F2 cycles the mode; the radius follows the rules.
#[allow(clippy::too_many_arguments)]
pub fn update(
    mut edge: ResMut<SightEdge>,
    keys: Res<ButtonInput<KeyCode>>,
    hud: Option<Res<crate::ui::model::HudModel>>,
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    rules: NonSend<crate::verbs::Rules>,
    clock: Res<crate::daylight::Clock>,
    loading: Option<Res<crate::loading::Loading>>,
    mut verbs: Option<ResMut<crate::verbs::Verbs>>,
    time: Res<Time>,
) {
    if keys.just_pressed(KeyCode::F2) {
        edge.mode = edge.mode.next();
        info!("sight edge: {:?} (radius {:.1} m)", edge.mode, edge.radius);
        if let Some(v) = verbs.as_deref_mut() {
            v.toasts.retain(|t| !t.text.starts_with("Edge of sight:"));
            v.toasts.push(crate::verbs::Toast { text: edge.mode.note(), ok: None, at: time.elapsed_secs_f64() });
        }
        edge.noted = true;
    }
    let dt = time.delta_secs();
    edge.next_ask -= dt;
    if edge.next_ask <= 0.0 {
        edge.next_ask = ASK_S;
        if let Some(r) = my_sight(&net, &rules, clock.hour()) {
            if edge.want.is_none() {
                edge.radius = r;
                info!("sight edge: sight {r:.1} m by the world's rules");
            } else if edge.want != Some(r) {
                info!("sight edge: sight {r:.1} m by the world's rules");
            }
            edge.want = Some(r);
        }
    }
    if let Some(w) = edge.want {
        edge.radius += (w - edge.radius) * (1.0 - (-dt * EASE).exp());
    }
    // Once I have arrived (my sight known, the first-load cover gone): the note, a little longer
    // than other notes.
    let arrived = edge.want.is_some() && hud.as_deref().is_some_and(|h| h.death.is_none()) && crate::loading::Loading::clear(loading.as_deref());
    if !edge.noted && arrived {
        if let Some(v) = verbs.as_deref_mut() {
            v.toasts.push(crate::verbs::Toast { text: edge.mode.note(), ok: None, at: time.elapsed_secs_f64() + NOTE_EXTRA_S });
            edge.noted = true;
            info!("sight edge: arrival note: {}", edge.mode.note());
        }
    }
    // For captures (`RUST_LOG=living_game::sightedge=debug`): how far the people drawn are.
    edge.next_report -= dt;
    if edge.next_report <= 0.0 && bevy::log::tracing::enabled!(bevy::log::Level::DEBUG) {
        edge.next_report = 2.0;
        if let Some(me) = net.my_id.and_then(|id| scene.shown.get(&id)).map(|s| s.0) {
            let mut d: Vec<f32> = scene.shown.iter().filter(|(id, _)| Some(**id) != net.my_id).map(|(_, s)| s.0.distance(me)).collect();
            d.sort_by(f32::total_cmp);
            let beyond = d.iter().filter(|x| **x > edge.radius).count();
            debug!("sight edge: radius {:.1} m; {} others shown, farthest {:.1} m, {} beyond the radius: {:?}", edge.radius, d.len(), d.last().copied().unwrap_or(0.0), beyond, d.iter().rev().take(6).map(|x| (x * 10.0).round() / 10.0).collect::<Vec<_>>());
        }
    }
}

/// Limited view stops drawing just past the fully fogged radius; the other modes keep the far
/// plane they had.
fn far(mut edge: ResMut<SightEdge>, target: Res<crate::controls::Target>, mut cams: Query<(&GlobalTransform, &mut Projection), With<Camera3d>>) {
    let Ok((gtf, mut proj)) = cams.single_mut() else { return };
    let Projection::Perspective(p) = &mut *proj else { return };
    match (edge.mode, target.0) {
        (Mode::Limited, Some(me)) if edge.want.is_some() => {
            let base = *edge.far.get_or_insert(p.far);
            let want = (gtf.translation().distance(me) + edge.radius * LIMIT + FAR_MARGIN).min(base);
            if (p.far - want).abs() > 0.05 {
                p.far = want;
            }
        }
        _ => {
            if let Some(base) = edge.far.take() {
                p.far = base;
            }
        }
    }
}

/// Feed the finishing pass (after `post::update` writes the rest of its settings).
fn shade(edge: Res<SightEdge>, field: Option<Res<crate::sightfield::SightField>>, target: Res<crate::controls::Target>, atmo: Option<Res<crate::daylight::Atmo>>, mut cams: Query<&mut crate::post::Edges>) {
    let Ok(mut e) = cams.single_mut() else { return };
    let me = target.0.filter(|_| edge.want.is_some());
    let mode = if me.is_some() { edge.mode.code() } else { 0.0 };
    let at = me.unwrap_or_default();
    e.sight = Vec4::new(at.x, at.z, edge.radius, mode);
    e.sight_look = Vec4::new(BAND_IN, BAND_OUT, DIM, DESATURATE);
    let sky = crate::camera::SKY.to_linear();
    let fog = atmo.filter(|a| a.active).map_or(Vec3::new(sky.red, sky.green, sky.blue), |a| a.fog);
    e.sight_fog = Vec4::new(fog.x, fog.y, fog.z, FLATTEN);
    e.sight_far = Vec4::new(LIMIT, SHADOW_FOG, 0.0, 0.0);
    e.sight_field = match field.as_deref().filter(|f| f.valid) {
        Some(f) => Vec4::new(f.origin.x as f32, f.origin.y as f32, 1.0 / crate::sightfield::EXTENT, 1.0),
        None => Vec4::ZERO,
    };
}

#[cfg(test)]
mod tests {
    use super::*;
    use living_rules::script::Scripts;

    #[test]
    fn modes_cycle_and_parse() {
        assert_eq!(Mode::Fade.next().next().next(), Mode::Fade);
        assert_eq!(Mode::default(), Mode::Unseen, "not seen now is the starting mode");
        assert!(Mode::Unseen.note().contains("F2"));
        assert_eq!(Mode::parse("unseen"), Some(Mode::Unseen));
        assert_eq!(Mode::parse(" Limited "), Some(Mode::Limited));
        assert_eq!(Mode::parse("other"), None);
    }

    /// The radius is the shipped law's answer: day, night, and a torch at night.
    #[test]
    fn sight_is_the_rules_answer() {
        let sc = Scripts::new(include_str!("../../scripts/skills.rhai")).unwrap();
        let ask = |night: bool, torch: bool| {
            let inv = if torch { vec![("torch".to_string(), 1)] } else { vec![] };
            let actor = ActorFacts { id: 1, kind: "person".into(), inv, ..Default::default() };
            sc.senses(&SkillCtx { actor, night, hour: if night { 23.0 } else { 12.0 }, ..Default::default() }).unwrap().sight
        };
        let (day, night, torch) = (ask(false, false), ask(true, false), ask(true, true));
        assert!(day > torch && torch > night, "day {day}, torch {torch}, night {night}");
        assert_eq!(ask(false, true), day, "a torch by day changes nothing");
    }
}
