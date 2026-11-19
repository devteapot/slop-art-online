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
//! - `silence`: "… could not have heard you." (`speech_truth`; "No answer from …" without it): `subject` the one I addressed, `object` me, written in the
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

/// A `silence` row ("… could not have heard you."): the one addressed, who did not hear me (0: a
/// line to the room no one heard, "Nobody was near enough to hear you.").
pub fn unheard(e: &Experience) -> Option<u32> {
    (e.kind == "silence").then_some(e.subject)
}

/// The spoken words of a percept such as `Helper said: “Welcome!”` (the whole text otherwise).
/// How a line to the room was said (speech-address), as the authority tells every hearer before
/// the words: "to the room, naming Ife and a stranger", "to the room while talking with Lorcan
/// Vane", or both; with a way's own tail ("…, from about 12 m"). Whatever follows "to the room" up
/// to the words is the detail, so "calling" or "naming" read alike. None for a line to someone
/// (its row names the addressee) or a room line said plainly.
pub fn how(text: &str) -> Option<&str> {
    let head = &text[..text.find('“')?];
    let at = head.find("to the room")?;
    let how = head[at..].trim_end().trim_end_matches(':').trim_end();
    (how.len() > "to the room".len()).then_some(how)
}

/// How a line to someone was said with more (talk-turns): the authority adds the detail after the
/// addressee, from the first comma before the words (", naming you", ", naming Agnes Fenner and
/// you"), whatever the verb or the way's template ("calls out to Bram from about 20 m, naming
/// you"). Labels carry no comma, so the first one starts the detail. None for a room line (see
/// [`how`]) or a line to someone said plainly. The window puts the addressee before it in the
/// player's own label ("to a stranger, naming you").
pub fn detail_to(text: &str) -> Option<&str> {
    let head = text[..text.find('“')?].trim_end().trim_end_matches(':').trim_end();
    if head.contains("to the room") {
        return None;
    }
    head.find(", ").map(|at| &head[at..])
}

pub fn words(text: &str) -> &str {
    match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => &text[a + '“'.len_utf8()..b],
        _ => text,
    }
}

/// One line for pacing: who said it, to whom (0: the room), when it was said (the row's
/// `at_ms`, authority ms) and its words.
#[derive(Clone, Copy, Debug)]
pub struct Spoken<'a> {
    pub speaker: u32,
    pub to: u32,
    pub at_ms: f64,
    pub words: &'a str,
}

impl<'a> Spoken<'a> {
    /// A line from a talk row: one I heard (`speech`) or my own (`said`); none for other rows.
    pub fn of(e: &'a Experience) -> Option<Self> {
        heard(e).or_else(|| said(e).map(|to| (e.subject, to))).map(|(speaker, to)| Spoken { speaker, to, at_ms: e.at_ms as f64, words: words(&e.text) })
    }
}

/// When a line's bubble shows, and how long it may last (reply-pace).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Paced {
    /// When the bubble first shows (authority ms): its `at_ms`, or later for a reply.
    pub shown_ms: f64,
    /// The line it answers (an index into the lines), when it is a reply.
    pub answers: Option<usize>,
    /// When a reply to it shows, which ends its bubble then (one bubble an exchange).
    pub cut_ms: Option<f64>,
}

/// Reply bubbles at speaking pace (reply-pace, docs/COMMUNICATION.md §21). Since reply-timing a
/// mind says a reply as soon as it is ready, so its row's `at_ms` can come well within the time
/// the line it answers takes to say, and both bubbles would be up at once. A reply's bubble shows
/// once the line it answers is done being said: at that line's showing plus its saying time
/// (`living_rules::saying::saying_ms`, 330 ms a word, at least 1.5 s), never before the reply's
/// own `at_ms`. For a line that is not itself paced (any line a player says, any room line) that
/// is its `at_ms`, the rule §21 gives; for a reply to a reply it is when that one showed, the
/// same place the mind gives a line in the exchange's rhythm (`voice`, `paced_ms`). The answered
/// line's bubble ends when its reply's shows: one bubble an exchange at a time.
///
/// The rows carry no reply-to link, so the line answered is inferred: the most recent line
/// before the reply from the one it is addressed to, to its speaker, with no line from its speaker
/// to them in between (a second line in a row is not a reply to the same line again). A line to
/// the room, or one to someone who said nothing to its speaker, is not a reply and shows at its
/// `at_ms`. A speaker's next line waits for their previous one only while that one is being
/// said: it shows no sooner after it than it was said after it, or than the previous line takes
/// to say, whichever is less (so a paced reply never hides the line before it at once, and its
/// delay does not carry over to the speaker's later lines).
///
/// `lines` must be in `at_ms` order; the answer is in the same order.
pub fn paced(lines: &[Spoken]) -> Vec<Paced> {
    let mut out: Vec<Paced> = Vec::with_capacity(lines.len());
    for (i, l) in lines.iter().enumerate() {
        let answers = (l.to != 0)
            .then(|| (0..i).rev().take_while(|&j| !(lines[j].speaker == l.speaker && lines[j].to == l.to)).find(|&j| lines[j].speaker == l.to && lines[j].to == l.speaker))
            .flatten();
        let mut shown_ms = answers.map_or(l.at_ms, |j| l.at_ms.max(out[j].shown_ms + living_rules::saying::saying_ms(lines[j].words) as f64));
        if let Some(prev) = (0..i).rev().find(|&j| lines[j].speaker == l.speaker) {
            let spacing = (l.at_ms - lines[prev].at_ms).min(living_rules::saying::saying_ms(lines[prev].words) as f64);
            shown_ms = shown_ms.max(out[prev].shown_ms + spacing);
        }
        if let Some(j) = answers {
            out[j].cut_ms = Some(out[j].cut_ms.map_or(shown_ms, |c| c.min(shown_ms)));
        }
        out.push(Paced { shown_ms, answers, cut_ms: None });
    }
    out
}

/// [`paced`] over talk rows (`speech` and `said`; other rows are left out): the rows in
/// `at_ms` order, each with its pacing.
pub fn pace_rows<'a>(rows: impl IntoIterator<Item = &'a Experience>) -> Vec<(&'a Experience, Spoken<'a>, Paced)> {
    let mut lines: Vec<(&Experience, Spoken)> = rows.into_iter().filter_map(|e| Spoken::of(e).map(|s| (e, s))).collect();
    lines.sort_by(|a, b| a.0.at_ms.cmp(&b.0.at_ms).then(a.0.id.cmp(&b.0.id)));
    let p = paced(&lines.iter().map(|(_, s)| *s).collect::<Vec<_>>());
    lines.into_iter().zip(p).map(|((e, s), p)| (e, s, p)).collect()
}

#[cfg(test)]
mod pace_tests {
    use super::{paced, Spoken};

    fn line(speaker: u32, to: u32, at_ms: f64, words: &str) -> Spoken<'_> {
        Spoken { speaker, to, at_ms, words }
    }

    #[test]
    fn a_reply_shows_once_the_line_it_answers_is_said_and_ends_that_bubble() {
        // The player (#1) greets a resident (#7) with nine words (2.97 s to say); the resident's
        // reply, said when ready, comes 0.6 s later.
        let greeting = "Good morning to you, how is the bread today?";
        let lines = [line(1, 7, 10_000.0, greeting), line(7, 1, 10_600.0, "Fresh as ever, come and see.")];
        let p = paced(&lines);
        assert_eq!(p[0].shown_ms, 10_000.0, "the player's own line shows as said");
        assert_eq!(p[1].shown_ms, 10_000.0 + 9.0 * 330.0, "the reply waits for the greeting's saying time");
        assert_eq!(p[1].answers, Some(0));
        assert_eq!(p[0].cut_ms, Some(p[1].shown_ms), "the greeting's bubble ends as the reply's shows");
        // A short line still takes the floor's 1.5 s.
        let p = paced(&[line(1, 7, 0.0, "Hi."), line(7, 1, 200.0, "Hello.")]);
        assert_eq!(p[1].shown_ms, 1_500.0);
        // A reply that comes after the saying time shows when it is said.
        let p = paced(&[line(1, 7, 0.0, greeting), line(7, 1, 4_000.0, "Fresh.")]);
        assert_eq!(p[1].shown_ms, 4_000.0);
        assert_eq!(p[0].cut_ms, Some(4_000.0));
    }

    #[test]
    fn lines_that_are_not_replies_show_as_said() {
        // A room line, a line to someone who said nothing to the speaker, and a line between
        // two others while the first speaker's line is up: none is paced.
        let lines = [line(1, 0, 0.0, "Good morning, all."), line(7, 1, 300.0, "Morning."), line(8, 9, 400.0, "Hand me that.")];
        let p = paced(&lines);
        assert_eq!(p.iter().map(|p| p.shown_ms).collect::<Vec<_>>(), vec![0.0, 300.0, 400.0]);
        assert!(p.iter().all(|p| p.answers.is_none() && p.cut_ms.is_none()));
    }

    #[test]
    fn the_answered_line_is_the_latest_to_the_replier_and_a_second_line_is_not_a_reply_again() {
        let lines = [
            line(1, 7, 0.0, "Where is the well?"),
            line(1, 7, 2_200.0, "The well, I mean, the one by the square?"),
            line(7, 1, 2_500.0, "By the bakery."),
            line(7, 1, 2_600.0, "Past the bakery."),
        ];
        let p = paced(&lines);
        // The reply answers the latest line to the resident (2.2 s, nine words: 2.97 s).
        assert_eq!(p[2].answers, Some(1));
        assert_eq!(p[2].shown_ms, 2_200.0 + 9.0 * 330.0);
        // The resident's second line answers nothing again, and keeps its 0.1 s after the first.
        assert_eq!(p[3].answers, None);
        assert_eq!(p[3].shown_ms, p[2].shown_ms + 100.0);
        assert_eq!(p[1].cut_ms, Some(p[2].shown_ms));
        assert_eq!(p[0].cut_ms, None);
    }

    #[test]
    fn a_paced_reply_does_not_delay_the_speakers_later_lines() {
        // The resident's reply is paced 4.3 s; its next line, 18 s later, shows when it is said
        // (reply-pace's first UI run: the follow-up call had been held 4.3 s too).
        let lines = [line(1, 7, 0.0, "Good morning to you, how is the bread at the bakery today? (rp-near)"), line(7, 1, 5.0, "Fresh as ever, come and see."), line(7, 1, 18_000.0, "Did you hear me? The cakes are gone.")];
        let p = paced(&lines);
        assert_eq!(p[1].shown_ms, 13.0 * 330.0);
        assert_eq!(p[2].shown_ms, 18_000.0);
    }

    #[test]
    fn a_reply_to_a_reply_is_paced_from_when_that_one_showed() {
        // Two residents: #7 asks, #8 answers when ready, #7 answers that 2.1 s after its own line.
        let lines = [line(7, 8, 0.0, "Is the bread ready yet, do you know?"), line(8, 7, 500.0, "Not yet, it needs an hour."), line(7, 8, 2_100.0, "Then I will wait.")];
        let p = paced(&lines);
        let first = 8.0 * 330.0;
        assert_eq!(p[1].shown_ms, first);
        assert_eq!(p[2].shown_ms, first + 6.0 * 330.0, "from when the answer showed, not from its at_ms");
        assert_eq!(p[0].cut_ms, Some(p[1].shown_ms));
        assert_eq!(p[1].cut_ms, Some(p[2].shown_ms));
    }
}

#[cfg(test)]
mod how_tests {
    use super::{detail_to, how, words};

    #[test]
    fn how_a_room_line_was_said_is_read_whatever_its_verb() {
        let naming = "Edda Hollin said to the room, naming Ife and a stranger: “Come and look.”";
        assert_eq!(how(naming), Some("to the room, naming Ife and a stranger"));
        assert_eq!(words(naming), "Come and look.");
        assert_eq!(how("A stranger said to the room, calling a stranger and you: “Here!”"), Some("to the room, calling a stranger and you"));
        assert_eq!(how("Edda said to the room while talking with Lorcan Vane: “Yes.”"), Some("to the room while talking with Lorcan Vane"));
        assert_eq!(how("Edda calls out to the room, naming you, from about 12 m: “Over here!”"), Some("to the room, naming you, from about 12 m"));
        // A line to someone, or to the room said plainly: no detail.
        assert_eq!(how("Edda said to you: “Hello.”"), None);
        assert_eq!(how("Edda said: “Morning.”"), None);
        assert_eq!(how("Bram said to the room: “Morning.”"), None);
    }

    #[test]
    fn a_line_to_someone_that_names_others_keeps_its_detail_whatever_its_verb() {
        let to_other = "Sissly Fenner said to a stranger, naming you: “Ask Mother first.”";
        assert_eq!(detail_to(to_other), Some(", naming you"));
        assert_eq!(how(to_other), None);
        assert_eq!(detail_to("Sissly Fenner said to you, naming Agnes Fenner and a stranger: “Ma knows.”"), Some(", naming Agnes Fenner and a stranger"));
        assert_eq!(detail_to("Bram calls out to someone too far away to make out from about 20 m, naming you: “Here!”"), Some(", naming you"));
        // Said plainly, or to the room: none here.
        assert_eq!(detail_to("Edda said to you: “Hello.”"), None);
        assert_eq!(detail_to("Bram calls out to Edda from about 20 m: “Here!”"), None);
        assert_eq!(detail_to("Edda said to the room, naming you: “Come.”"), None);
        assert_eq!(detail_to("Edda said: “Morning.”"), None);
    }
}
