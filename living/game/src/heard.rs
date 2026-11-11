//! Readers of the authority's records of talk that the client shows in the person windows and
//! the log, in one place. Two of them are agreed with the Spark coordinator (2026-11-11,
//! `.local/living/ui-designs/DECISION.md`) and **not in the authority yet**; their names are
//! not final, so only this module changes when they land:
//!
//! - **`heard_by`:** a list of character ids on the speaker's own `said` experience row, the
//!   hearers the speaker perceived at that moment. Until it exists, [`heard_by`] says "not
//!   reported" (`None`) and the windows show nothing under a line. When it lands, ids map
//!   through the projection's labels (`looks.rs`), and an addressee missing from it means
//!   "addressed, not heard".
//! - **`introduced`:** an experience row for the learner when someone tells it their name,
//!   keyed on the speaker as subject ("Mercy told you her name"). Read by kind now, so the row
//!   shows as soon as the authority writes it; until then no window says how a name was learned.
//!
//! Already in the authority (docs/PERCEPTION.md, `perceive::speak`):
//! - `said`: my own line; `subject` me, `object` whom I addressed (0: no one in particular);
//! - `speech`: a line I heard; `subject` the speaker, `object` whom they addressed;
//! - `silence`: "No answer from …": `subject` the one I addressed, `object` me, written in the
//!   same instant as my `said` row when they were out of earshot.

use living_bindings::Experience;

/// The hearers the speaker perceived, from the speaker's `said` row: not reported yet.
pub fn heard_by(e: &Experience) -> Option<Vec<u32>> {
    let _ = e;
    None
}

/// Whose name I learned from this row, if it is an introduction.
pub fn introduced(e: &Experience) -> Option<u32> {
    (e.kind == "introduced").then_some(e.subject)
}

/// My own line: whom it addressed (0: no one in particular).
pub fn said(e: &Experience) -> Option<u32> {
    (e.kind == "said").then_some(e.object)
}

/// A line I heard: the speaker, and whom they addressed (0: no one in particular).
pub fn heard(e: &Experience) -> Option<(u32, u32)> {
    (e.kind == "speech").then_some((e.subject, e.object))
}

/// "No answer from …": the one addressed, who did not hear me.
pub fn unheard(e: &Experience) -> Option<u32> {
    (e.kind == "silence").then_some(e.subject)
}

/// The spoken words of a percept such as `Helper said: “Welcome!”` (the whole text otherwise).
pub fn words(text: &str) -> &str {
    match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => &text[a + '“'.len_utf8()..b],
        _ => text,
    }
}
