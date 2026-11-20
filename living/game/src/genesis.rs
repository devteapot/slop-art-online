//! A world still being made (staged genesis, docs/STAGED_GENESIS.md §4): the client waits, shows
//! how far it is, and joins once it is ready.
//!
//! A freshly published world is made by scheduled steps after the publish returns (the island
//! about 17–22 s, Cullet about 11 s). Until its public `genesis` row (one row, `id` 0) says
//! `done`, the authority refuses `join`, `join_as`, the `human_*` reducers, `use_skill` and
//! `release_skill` with `world_preparing: the world is still being made (step i of n: label)`.
//! Clients match the prefix [`PREPARING`]; the rest is for people.
//!
//! The client (`net.rs`):
//! - subscribes `SELECT * FROM genesis` on connect, as its own subscription beside the static set
//!   (a module from before staged genesis has no such table: that one subscription fails, quietly,
//!   and the world counts as ready, as the authority's `floor::ready` counts a world with no row);
//! - holds the base set, and so `join`, until the world is ready: a half-made world has no `land`
//!   row yet (the world's kind would be guessed wrong) and its chunks are still being written;
//! - if a call is refused with `world_preparing` all the same (the row was missed, or a reconnect
//!   raced it), it is never a player-facing failure: [`Wait::refused`] takes the progress from the
//!   error text and `join` is sent again when `done` turns true, or on a backoff
//!   ([`BACKOFF_S`], doubling to [`BACKOFF_MAX_S`]) in case the row's update is missed;
//! - the cover (`loading.rs`) and, after a reconnect, the link line say "Preparing the world…"
//!   with the step, the steps, the label and a bar; after [`TIMEOUT_S`] they say it is taking
//!   long and keep waiting (a stopped chain, a label `stopped: …`, is said at once).

/// The stable refusal code's prefix (`floor::PREPARING` on the authority).
pub const PREPARING: &str = "world_preparing";
/// The first retry after a refusal (s); each further one doubles, up to [`BACKOFF_MAX_S`].
pub const BACKOFF_S: f64 = 1.0;
pub const BACKOFF_MAX_S: f64 = 5.0;
/// How long the world may be preparing before the client says it is taking long (s). It keeps
/// waiting after that: the cover has no buttons, and joining when the world is ready is what a
/// player would choose.
pub const TIMEOUT_S: f64 = 120.0;

/// Whether a reducer's error is the authority's "the world is still being made".
pub fn is_preparing(err: &str) -> bool {
    err.trim_start().starts_with(PREPARING)
}

/// How far genesis is, from the row or from a refusal's text.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Progress {
    pub step: u32,
    pub steps: u32,
    pub label: String,
}

impl Progress {
    pub fn of_row(g: &living_bindings::Genesis) -> Self {
        // As the authority's refusal says it: `steps` grows once a land's wards are known.
        Progress { step: g.step, steps: g.steps.max(g.step + 1), label: g.label.clone() }
    }

    /// From `world_preparing: the world is still being made (step 3 of 40: land: ward 2)`;
    /// None when it is not a `world_preparing` refusal. A text that does not parse further gives
    /// an empty progress (the refusal still counts).
    pub fn of_refusal(err: &str) -> Option<Self> {
        if !is_preparing(err) {
            return None;
        }
        let parsed = (|| {
            let rest = &err[err.find("(step ")? + "(step ".len()..];
            let (step, rest) = rest.split_once(" of ")?;
            let (steps, rest) = rest.split_once(':').map_or_else(|| rest.split_once(')').map(|(s, _)| (s, "")), Some)?;
            let label = rest.trim().strip_suffix(')').unwrap_or(rest.trim()).trim();
            Some(Progress { step: step.trim().parse().ok()?, steps: steps.trim().trim_end_matches(')').parse().ok()?, label: label.to_string() })
        })();
        Some(parsed.unwrap_or_default())
    }

    /// Done steps as a share, 0..=1 (0 when the steps are not known).
    pub fn share(&self) -> f32 {
        if self.steps == 0 { 0.0 } else { (self.step as f32 / self.steps as f32).clamp(0.0, 1.0) }
    }

    /// A stopped chain (a failed step) says so in its label.
    pub fn stopped(&self) -> bool {
        self.label.starts_with("stopped")
    }

    /// "step 3 of 40 · land: ward 2", or what is known of it.
    pub fn line(&self) -> String {
        match (self.steps, self.label.is_empty()) {
            (0, true) => String::new(),
            (0, false) => self.label.clone(),
            (_, true) => format!("step {} of {}", self.step, self.steps),
            (_, false) => format!("step {} of {} · {}", self.step, self.steps, self.label),
        }
    }
}

/// Whether the world is known to be ready.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Gate {
    /// The `genesis` subscription has not answered yet.
    Unknown,
    Preparing,
    Ready,
}

/// What the client should do now about `join`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Retry {
    None,
    /// Send `join` again: the world turned ready after a refusal, or the backoff ran out.
    Join,
}

/// The waiting state of one connection (reset on a new connection).
#[derive(Clone, Debug)]
pub struct Wait {
    pub gate: Gate,
    pub progress: Option<Progress>,
    /// When preparing was first seen (elapsed s).
    pub since: Option<f64>,
    /// When `done` was seen after preparing (elapsed s), for the time from done to join.
    pub done_at: Option<f64>,
    /// A refused `join` waiting to be sent again: when, and how many refusals so far.
    retry_at: Option<f64>,
    refusals: u32,
    /// The row itself was seen not done: its turning done is the signal to join at once. (A
    /// refusal while the row says ready or is absent waits for the backoff instead, so a stale
    /// refusal can never become a loop.)
    row_preparing: bool,
    /// Whether the "taking long" line was logged.
    pub told_long: bool,
    /// The bar's share: the most done seen, so it never runs back when `steps` grows once a
    /// land's wards are known (16 of 24, then 17 of 40). The line says the steps as they are.
    pub bar: f32,
}

impl Default for Wait {
    fn default() -> Self {
        Wait { gate: Gate::Unknown, progress: None, since: None, done_at: None, retry_at: None, refusals: 0, row_preparing: false, told_long: false, bar: 0.0 }
    }
}

impl Wait {
    pub fn ready(&self) -> bool {
        self.gate == Gate::Ready
    }

    pub fn preparing(&self) -> bool {
        self.gate == Gate::Preparing
    }

    /// The `genesis` subscription answered (`row` the `id` 0 row, None when there is none: a
    /// world made before staged genesis, or a floor not yet given its seed).
    pub fn row(&mut self, row: Option<Progress>, done: bool, now: f64) {
        match row {
            Some(p) if !done => {
                self.row_preparing = true;
                self.preparing_at(p, now);
            }
            _ => self.turn_ready(now),
        }
    }

    /// The `genesis` subscription failed: a module without the table, so a world made before
    /// staged genesis. A refusal still says otherwise ([`Wait::refused`]).
    pub fn no_table(&mut self, now: f64) {
        if self.gate == Gate::Unknown {
            self.turn_ready(now);
        }
    }

    /// A call refused with `world_preparing`. Returns whether it was one (the caller then keeps
    /// it from the player). A refused `join` is sent again when the world turns ready, or after
    /// the backoff.
    pub fn refused(&mut self, err: &str, join: bool, now: f64) -> bool {
        let Some(from_text) = Progress::of_refusal(err) else { return false };
        // The row, when in, is newer than any refusal's text.
        let p = match &self.progress {
            Some(row) if self.gate == Gate::Preparing => row.clone(),
            _ => from_text,
        };
        self.preparing_at(p, now);
        if join {
            self.refusals += 1;
            self.retry_at = Some(now + backoff(self.refusals));
        }
        true
    }

    /// Whether to send `join` again now.
    pub fn poll(&mut self, now: f64) -> Retry {
        let Some(at) = self.retry_at else { return Retry::None };
        if (self.gate == Gate::Ready && self.row_preparing) || now >= at {
            self.retry_at = None;
            return Retry::Join;
        }
        Retry::None
    }

    /// Preparing for longer than [`TIMEOUT_S`].
    pub fn long(&self, now: f64) -> bool {
        self.preparing() && self.since.is_some_and(|s| now - s > TIMEOUT_S)
    }

    /// What the cover or the link line says: a title and a detail line, while preparing.
    pub fn text(&self, now: f64) -> Option<(String, String)> {
        if !self.preparing() {
            return None;
        }
        let p = self.progress.clone().unwrap_or_default();
        let line = p.line();
        if p.stopped() {
            return Some(("The world could not be made".into(), format!("{line}\nIts making stopped; it will join if the world is made after all.")));
        }
        if self.long(now) {
            let mins = ((now - self.since.unwrap_or(now)) / 60.0).floor().max(2.0) as u32;
            return Some(("Preparing the world…".into(), format!("{line}\nThis is taking longer than usual ({mins} min). Still waiting: you join as soon as it is ready.")));
        }
        Some(("Preparing the world…".into(), line))
    }

    fn preparing_at(&mut self, p: Progress, now: f64) {
        if self.gate != Gate::Preparing {
            self.since.get_or_insert(now);
            self.done_at = None;
        }
        self.gate = Gate::Preparing;
        self.bar = self.bar.max(p.share());
        self.progress = Some(p);
    }

    fn turn_ready(&mut self, now: f64) {
        if self.gate == Gate::Preparing {
            self.done_at = Some(now);
        }
        self.gate = Gate::Ready;
    }
}

/// The wait before the `n`th retry (n ≥ 1): 1, 2, 4, 5, 5… s.
pub fn backoff(n: u32) -> f64 {
    (BACKOFF_S * 2f64.powi(n.saturating_sub(1).min(16) as i32)).min(BACKOFF_MAX_S)
}

#[cfg(test)]
mod tests {
    use super::*;

    const REFUSAL: &str = "world_preparing: the world is still being made (step 3 of 40: land: ward 2 of 9)";

    #[test]
    fn the_prefix_is_matched_and_the_rest_is_for_people() {
        assert!(is_preparing(REFUSAL));
        assert!(is_preparing("world_preparing"));
        assert!(!is_preparing("join refused: world_preparing"), "only the prefix of the reducer's own error");
        assert!(!is_preparing("you already have a living character"));
        assert_eq!(Progress::of_refusal(REFUSAL), Some(Progress { step: 3, steps: 40, label: "land: ward 2 of 9".into() }));
        // A label with its own parentheses keeps them.
        assert_eq!(
            Progress::of_refusal("world_preparing: the world is still being made (step 0 of 23: build (lots))").unwrap(),
            Progress { step: 0, steps: 23, label: "build (lots)".into() }
        );
        // No label.
        assert_eq!(Progress::of_refusal("world_preparing: being made (step 1 of 2)").unwrap(), Progress { step: 1, steps: 2, label: String::new() });
        // A text that changed shape still counts, with nothing known.
        assert_eq!(Progress::of_refusal("world_preparing: later wording"), Some(Progress::default()));
        assert_eq!(Progress::of_refusal("admin only"), None);
    }

    #[test]
    fn progress_lines_and_shares() {
        let p = Progress { step: 10, steps: 40, label: "chunks: 16384".into() };
        assert_eq!(p.line(), "step 10 of 40 · chunks: 16384");
        assert!((p.share() - 0.25).abs() < 1e-6);
        assert_eq!(Progress::default().share(), 0.0);
        assert_eq!(Progress::default().line(), "");
        assert!(Progress { label: "stopped: out of energy".into(), ..p }.stopped());
    }

    #[test]
    fn the_row_moves_the_gate_and_done_is_timed() {
        let mut w = Wait::default();
        assert_eq!(w.gate, Gate::Unknown);
        assert!(w.text(0.0).is_none());
        w.row(Some(Progress { step: 1, steps: 40, label: "land".into() }), false, 1.0);
        assert!(w.preparing());
        assert_eq!(w.since, Some(1.0));
        let (title, detail) = w.text(2.0).unwrap();
        assert_eq!(title, "Preparing the world…");
        assert_eq!(detail, "step 1 of 40 · land");
        w.row(Some(Progress { step: 16, steps: 24, label: "land: plan: paint".into() }), false, 8.0);
        w.row(Some(Progress { step: 17, steps: 40, label: "land: plan: walled connectivity".into() }), false, 8.5);
        assert!((w.bar - 16.0 / 24.0).abs() < 1e-6, "the bar never runs back when the steps grow");
        w.row(Some(Progress { step: 20, steps: 40, label: "resources".into() }), false, 9.0);
        assert_eq!(w.since, Some(1.0), "preparing since the first sight");
        w.row(Some(Progress { step: 40, steps: 41, label: "done".into() }), true, 18.5);
        assert!(w.ready());
        assert_eq!(w.done_at, Some(18.5));
        assert!(w.text(19.0).is_none());
    }

    #[test]
    fn no_row_or_no_table_is_ready() {
        let mut w = Wait::default();
        w.row(None, false, 0.5);
        assert!(w.ready());
        assert_eq!(w.done_at, None, "never preparing");
        let mut old = Wait::default();
        old.no_table(0.5);
        assert!(old.ready());
        // A late subscription error never undoes a seen row.
        let mut seen = Wait::default();
        seen.row(Some(Progress::default()), false, 0.0);
        seen.no_table(1.0);
        assert!(seen.preparing());
    }

    #[test]
    fn a_refused_join_is_sent_again_when_done_turns_true() {
        let mut w = Wait::default();
        w.no_table(0.0);
        // The row was missed: the refusal says preparing, with its own progress.
        assert!(w.refused(REFUSAL, true, 1.0));
        assert!(w.preparing());
        assert_eq!(w.progress.as_ref().unwrap().step, 3);
        assert_eq!(w.poll(1.5), Retry::None);
        // The row arrives, still preparing, then done: join at once, before the backoff.
        w.row(Some(Progress { step: 30, steps: 40, label: "populate".into() }), false, 1.6);
        assert_eq!(w.poll(1.7), Retry::None);
        w.row(Some(Progress { step: 40, steps: 40, label: "done".into() }), true, 1.8);
        assert_eq!(w.poll(1.8), Retry::Join);
        assert_eq!(w.poll(1.9), Retry::None, "once");
    }

    #[test]
    fn a_refused_join_is_retried_on_a_capped_backoff() {
        assert_eq!([1, 2, 3, 4, 9].map(backoff), [1.0, 2.0, 4.0, 5.0, 5.0]);
        let mut w = Wait::default();
        w.refused(REFUSAL, true, 10.0);
        assert_eq!(w.poll(10.9), Retry::None);
        assert_eq!(w.poll(11.0), Retry::Join);
        w.refused(REFUSAL, true, 11.1);
        assert_eq!(w.poll(13.0), Retry::None);
        assert_eq!(w.poll(13.1), Retry::Join);
    }

    #[test]
    fn a_refusal_against_a_ready_row_waits_for_the_backoff() {
        let mut w = Wait::default();
        w.row(None, false, 0.0);
        w.refused(REFUSAL, true, 1.0);
        // The next frame reads the row again: absent, so ready; the join waits its backoff.
        w.row(None, false, 1.01);
        assert!(w.ready());
        assert_eq!(w.poll(1.02), Retry::None);
        assert_eq!(w.poll(2.0), Retry::Join);
    }

    #[test]
    fn other_refused_calls_are_held_quietly_without_a_join() {
        let mut w = Wait::default();
        w.row(Some(Progress { step: 5, steps: 40, label: "land".into() }), false, 0.0);
        assert!(w.refused("world_preparing: the world is still being made (step 2 of 40: land)", false, 1.0));
        assert_eq!(w.progress.as_ref().unwrap().step, 5, "the row is newer than the text");
        assert_eq!(w.poll(100.0), Retry::None);
        assert!(!w.refused("too far away", false, 2.0), "other refusals are the player's");
    }

    #[test]
    fn a_long_wait_and_a_stopped_chain_are_said() {
        let mut w = Wait::default();
        w.row(Some(Progress { step: 5, steps: 40, label: "land".into() }), false, 0.0);
        assert!(!w.long(TIMEOUT_S - 1.0));
        assert!(w.long(TIMEOUT_S + 1.0));
        assert!(w.text(TIMEOUT_S + 1.0).unwrap().1.contains("taking longer than usual (2 min)"));
        w.row(Some(Progress { step: 6, steps: 40, label: "stopped: out of energy".into() }), false, 3.0);
        assert_eq!(w.text(3.0).unwrap().0, "The world could not be made");
    }
}
