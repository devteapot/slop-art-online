//! Sight that depends on facing (docs/PERCEPTION.md, "The field of view"), as the client shows it.
//! Presentation only: the authority decides whom I perceive (`living_rules::sight::sees`); the
//! client draws the same rule from the same law.
//!
//! - **Whether it is on:** the world's `fov_on` law. While it is on, `senses(a)` (the installed
//!   script, compiled by `verbs.rs`) returns a `field` with five values: `focal_deg`,
//!   `side_deg`, `side_share`, `near_m` and `margin_deg`. `sightedge.rs` asks the law;
//!   `sightfield.rs` draws its three zones (focal, side at `side_share` of sight, near all
//!   round) in the unseen-ground look. Off (the shipped default), nothing changes.
//! - **The readout:** when the field changes (on, off, or a value), a note says "Facing sight on"
//!   or "off", and a second gives the five values; both fade after a few seconds (the toasts,
//!   `ui/verbs.rs`). Settings › Play shows them for as long as it is on (`ui/facing.rs`).
//! - **The switch:** `set_world_law("fov_on", …)` is admin only; a player's connection can't
//!   call it, and the rules give players no such right. The play launcher (`living/tools/play.py`,
//!   a scene's `"law_toggle": true`) hands the client the world admin's token in a file
//!   (`LIVING_GAME_ADMIN_TOKEN_FILE`), for its own scratch `verify-*` world only; the client then
//!   opens a second connection with it, used for nothing but that call. F5, or the toggle in
//!   Settings › Play, asks it. Without the file (normal play), the switch is read-only and F5
//!   only says so.
//! - **The look input:** `human_face(dx, dy)` is not in the rules yet; until it is, the field
//!   follows `body.heading` (the travel direction, or a `face` gesture), also when facing the
//!   cursor. Settings says so beside the control scheme. It plugs in at `controls::look`.

use crate::net::Net;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::sight::Field;
use std::sync::{Arc, Mutex};

/// The key that asks the world's `fov_on` law to switch (with the admin link only).
pub const KEY: KeyCode = KeyCode::F5;

/// Facing sight as this client knows it.
#[derive(Resource, Default)]
pub struct FovState {
    /// Whether my senses are known yet (the script and my character).
    pub known: bool,
    /// The field my senses have now: `Some` while the world's `fov_on` law is on.
    pub field: Option<Field>,
    /// How many times the field changed since joining (the readout showed each).
    pub changes: u32,
    /// A switch asked for (on or off), sent by the admin link.
    pub ask: Option<bool>,
    /// The admin link is open: the switch works.
    pub can_switch: bool,
    /// Whether the launcher gave this client an admin token at all.
    pub offered: bool,
    /// The last answer to a switch ("fov_on → true: done", or the refusal).
    pub last: Option<String>,
}

impl FovState {
    pub fn on(&self) -> bool {
        self.field.is_some()
    }
}

/// The five values in a line, for the readout and Settings.
pub fn values(f: &Field) -> String {
    format!(
        "Focal ±{:.0}° · side ±{:.0}° at {:.0}% of sight · near {} m all round · margin {:.0}°",
        f.focal_deg,
        f.side_deg,
        f.side_share * 100.0,
        trim(f.near_m),
        f.margin_deg
    )
}

fn trim(v: f32) -> String {
    let s = format!("{v:.1}");
    s.strip_suffix(".0").map(str::to_string).unwrap_or(s)
}

/// The second connection, as the world's admin, for `set_world_law` only.
#[derive(Default)]
pub struct AdminLink {
    conn: Option<DbConnection>,
    inbox: Arc<Mutex<Vec<Signal>>>,
    started: bool,
}

enum Signal {
    Built(Result<DbConnection, String>),
    Connected,
    Gone(String),
    Reply(bool, Result<(), String>),
}

pub struct FacingPlugin;

impl Plugin for FacingPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<FovState>()
            .init_non_send::<AdminLink>()
            .add_systems(Update, (watch, keys, link).chain().in_set(crate::phase::Phase::Camera).after(crate::sightedge::update));
    }
}

/// The field from my senses: on a change, the note and the readout.
fn watch(mut st: ResMut<FovState>, edge: Res<crate::sightedge::SightEdge>, mut verbs: Option<ResMut<crate::verbs::Verbs>>, time: Res<Time>) {
    let Some(s) = edge.senses else { return };
    if st.known && st.field == s.field {
        return;
    }
    let first = !st.known;
    st.known = true;
    st.field = s.field;
    // On arrival with facing sight off there is nothing to say: the world is as it always was.
    if first && s.field.is_none() {
        return;
    }
    st.changes += 1;
    let note = if s.field.is_some() { "Facing sight on" } else { "Facing sight off" };
    let readout = s.field.map(|f| values(&f));
    info!("facing: {note}{}", readout.as_deref().map(|r| format!(" — {r}")).unwrap_or_default());
    if let Some(v) = verbs.as_deref_mut() {
        let at = time.elapsed_secs_f64();
        v.toasts.retain(|t| !t.text.starts_with("Facing sight") && !t.text.starts_with("Focal ±"));
        v.toasts.push(crate::verbs::Toast { text: format!("{note}  ·  {}", if st.can_switch { "F5 switches it" } else { "the world's law" }), ok: None, at });
        if let Some(r) = readout {
            v.toasts.push(crate::verbs::Toast { text: r, ok: None, at });
        }
    }
}

/// F5 asks for the switch.
fn keys(mut st: ResMut<FovState>, keys: Res<ButtonInput<KeyCode>>, input: Res<crate::controls::Input>, cap: Option<Res<crate::ui::settings::Capture>>) {
    // Not while typing, nor while Settings waits for a key to bind.
    if input.chat_open || cap.is_some_and(|c| c.listening()) || !keys.just_pressed(KEY) {
        return;
    }
    let want = !st.on();
    ask(&mut st, want);
}

/// Ask the world's `fov_on` law to be `on` (F5, or the toggle in Settings › Play).
pub fn ask(st: &mut FovState, on: bool) {
    if !st.can_switch {
        info!("facing: switch asked ({on}) but this client has no admin link: read-only");
        st.last = Some(if st.offered { "The admin link is not open (yet)".into() } else { "Read-only: only a play scene's launcher can switch the world's law".into() });
        return;
    }
    st.ask = Some(on);
}

/// The admin link: opened once when the launcher gave a token, then `set_world_law` for asks.
fn link(mut admin: NonSendMut<AdminLink>, mut st: ResMut<FovState>, net: NonSend<Net>, mut verbs: Option<ResMut<crate::verbs::Verbs>>, time: Res<Time>) {
    if !admin.started {
        admin.started = true;
        let Some(path) = std::env::var("LIVING_GAME_ADMIN_TOKEN_FILE").ok().filter(|p| !p.is_empty()) else { return };
        // Only a scratch world: never a reference world or the owner's other worlds.
        if !net.db.starts_with("verify-") {
            warn!("facing: an admin token was given for {}, which is not a verify-* world: the switch stays read-only", net.db);
            return;
        }
        st.offered = true;
        let token = match std::fs::read_to_string(&path) {
            Ok(t) if !t.trim().is_empty() => t.trim().to_string(),
            _ => {
                warn!("facing: could not read the admin token file: the switch stays read-only");
                return;
            }
        };
        let (built, connected, gone, failed) = (admin.inbox.clone(), admin.inbox.clone(), admin.inbox.clone(), admin.inbox.clone());
        let builder = DbConnection::builder()
            .with_uri(net.server.clone())
            .with_database_name(net.db.clone())
            .with_token(Some(token))
            .on_connect(move |_, _, _| connected.lock().unwrap().push(Signal::Connected))
            .on_disconnect(move |_, e| gone.lock().unwrap().push(Signal::Gone(e.map(|e| e.to_string()).unwrap_or_else(|| "closed".into()))))
            .on_connect_error(move |_, e| failed.lock().unwrap().push(Signal::Gone(format!("connect failed: {e}"))));
        info!("facing: opening the admin link to {} (set_world_law only)", net.db);
        std::thread::spawn(move || {
            let r = builder.build().map_err(|e| e.to_string());
            built.lock().unwrap().push(Signal::Built(r));
        });
    }
    if let Some(conn) = admin.conn.as_ref() {
        if let Err(e) = conn.frame_tick() {
            admin.inbox.lock().unwrap().push(Signal::Gone(e.to_string()));
        }
    }
    let signals: Vec<Signal> = std::mem::take(&mut *admin.inbox.lock().unwrap());
    for s in signals {
        match s {
            Signal::Built(Ok(c)) => admin.conn = Some(c),
            Signal::Built(Err(e)) | Signal::Gone(e) => {
                warn!("facing: the admin link is closed: {e}");
                admin.conn = None;
                st.can_switch = false;
            }
            Signal::Connected => {
                info!("facing: admin link open: F5 and Settings › Play switch facing sight");
                st.can_switch = true;
            }
            Signal::Reply(on, r) => {
                let msg = match &r {
                    Ok(()) => format!("fov_on → {on}: done"),
                    Err(e) => format!("fov_on → {on} refused: {e}"),
                };
                info!("facing: set_world_law {msg}");
                if r.is_err() {
                    if let Some(v) = verbs.as_deref_mut() {
                        v.toasts.push(crate::verbs::Toast { text: format!("Facing sight: {msg}"), ok: Some(false), at: time.elapsed_secs_f64() });
                    }
                }
                st.last = Some(msg);
            }
        }
    }
    if let (Some(on), Some(conn)) = (st.ask.take(), admin.conn.as_ref()) {
        info!("facing: asking set_world_law(\"fov_on\", \"{on}\")");
        let inbox = admin.inbox.clone();
        let r = conn.reducers.set_world_law_then("fov_on".into(), on.to_string(), move |_, r| {
            let r = match r {
                Ok(o) => o,
                Err(e) => Err(e.to_string()),
            };
            inbox.lock().unwrap().push(Signal::Reply(on, r));
        });
        if let Err(e) = r {
            warn!("facing: set_world_law could not be sent: {e}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_readout_names_all_five_values() {
        let f = Field { focal_deg: 70.0, side_deg: 110.0, side_share: 1.0 / 3.0, near_m: 3.0, margin_deg: 10.0 };
        assert_eq!(values(&f), "Focal ±70° · side ±110° at 33% of sight · near 3 m all round · margin 10°");
        let g = Field { near_m: 2.5, ..f };
        assert!(values(&g).contains("near 2.5 m"));
    }
}
