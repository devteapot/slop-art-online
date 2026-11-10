//! The order of a connected frame (`Update`), as named sets:
//!
//! 1. [`Phase::Net`]: the connection's `frame_tick` applies what arrived (`net::pump`).
//! 2. [`Phase::Mirror`]: the client's own state taken from the rows: the display clock and body
//!    tracks, where I stand, the skill cards, perceived combat events, town rows.
//! 3. [`Phase::Input`]: keys, mouse, scripts and the UI's requests become reducer calls.
//! 4. [`Phase::Flush`]: those calls leave this frame (`net::flush`, docs/LATENCY.md step 1).
//! 5. [`Phase::Present`]: what each body plays and where it is drawn, from this frame's rows and
//!    inputs, so a move pressed or perceived in a frame shows in that frame.
//! 6. [`Phase::Camera`]: the camera follows what was drawn; the cursor's ground point and the
//!    aim indicators come from it.
//!
//! Look-dev and the asset view use their own chains and leave these sets unconfigured.

use bevy::prelude::*;

#[derive(SystemSet, Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Phase {
    Net,
    Mirror,
    Input,
    Flush,
    Present,
    Camera,
}

/// Order the sets, once, for connected play.
pub fn configure(app: &mut App) {
    app.configure_sets(Update, (Phase::Net, Phase::Mirror, Phase::Input, Phase::Flush, Phase::Present, Phase::Camera).chain());
}
