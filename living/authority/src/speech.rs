//! Speech (docs/COMMUNICATION.md): one primitive, [`speak`], applies the script's ways of
//! speaking (`<way>_speech()`, read once per script revision as `WaySpec`s). It checks what the
//! way requires, gathers the listeners within the way's widest carry, gives each one its
//! reception (the words, the gist, a voice, or nothing) as an experience row in its own terms,
//! and leaves the trace: the speaker's `said` row, the `heard` row (who received the words
//! that the speaker saw), the chronicle line, and introductions. Players (`human_say`,
//! `human_speak`), minds (`mind_say`, `mind_install`) and behaviour graphs (`say` nodes) all
//! speak through it.

use crate::common::{self, direction, pos};
use crate::perceive::percept;
use crate::tables::*;
use living_rules::outcome::{act as code, kind};
use living_rules::script::speech::{To, WaySpec, SAY};
use spacetimedb::{ReducerContext, Table, ViewContext};

/// The shortest gap between two lines one speaker says, whatever the way (ms). A way's own
/// `gap_s` can only make it longer.
pub const SPEAK_GAP_MS: u64 = 2_000;

/// How long a line's `audience` row is kept (`speech_audience`).
const AUDIENCE_KEEP_MS: u64 = 60_000;

/// The way a name stands for (`""` is `say`).
fn way_name(way: &str) -> &str {
    if way.is_empty() {
        SAY
    } else {
        way
    }
}

/// How long ago `speaker` last said a line of `way` (its `heard` rows), when it has.
fn since_ms(ctx: &ReducerContext, speaker: u32, way: &str, now: u64) -> Option<u64> {
    ctx.db.line_heard().speaker().filter(speaker).filter(|h| h.way == way).map(|h| h.at_ms).max().map(|at| now.saturating_sub(at))
}

/// The way's own refusal of a line, in the script's words (`<way>_check`), as a client sees it
/// before sending: `Err` with exactly those words.
fn way_check(ctx: &ReducerContext, sc: &living_rules::script::Scripts, w: &WaySpec, speaker: u32, to: u32, text: &str, now: u64) -> Result<(), String> {
    if !sc.has(&format!("{}_check", w.name)) {
        return Ok(());
    }
    let (actor, addressee) = crate::act::way_facts(ctx, speaker, &w.name, to, now);
    living_rules::script::speech::check_way(sc, &w.name, actor, addressee, text, since_ms(ctx, speaker, &w.name, now))
}

/// Whether `speaker` must still wait before its next line of `way`: the 2 s speaking limit, or
/// the way's own check refuses a line now (a call within its gap).
pub fn too_soon_to_speak(ctx: &ReducerContext, speaker: u32, way: &str, now: u64) -> bool {
    if ctx.db.mind_state().id().find(speaker).is_some_and(|st| now.saturating_sub(st.spoke_ms) < SPEAK_GAP_MS) {
        return true;
    }
    let sc = common::scripts(ctx);
    let Some(w) = sc.way(way_name(way)) else { return false };
    let gap = (w.gap_s * 1000.0) as u64;
    gap > SPEAK_GAP_MS && since_ms(ctx, speaker, &w.name, now).is_some_and(|ago| ago < gap)
}

/// `{a}` (the speaker) and `{b}` (the addressee) in a way's words, as `reader` refers to them,
/// and `{d}` how far the speaker is from the reader (whole metres); an `{a}` that begins the
/// sentence is capitalized.
fn fill(ctx: &ReducerContext, template: &str, reader: &Character, a: u32, b: u32, d: f32) -> String {
    let mut t = template.to_string();
    if t.contains("{d}") {
        t = t.replace("{d}", &format!("{:.0}", d.max(1.0)));
    }
    if t.contains("{b}") {
        t = t.replace("{b}", &common::label_for(ctx, reader, b));
    }
    if t.starts_with("{a}") {
        t = t.replacen("{a}", &common::label_cap(ctx, reader, a), 1);
    }
    if t.contains("{a}") {
        t = t.replace("{a}", &common::label_for(ctx, reader, a));
    }
    t
}

/// Say `text` to `to` (0: the room) in `way` (`""`: `say`). `Err` refuses the line, in the
/// world's words, and writes nothing.
pub fn speak(ctx: &ReducerContext, speaker: u32, text: &str, to: u32, way: &str, now: u64) -> Result<(), String> {
    let text = text.trim();
    if text.is_empty() {
        return Ok(());
    }
    let sc = common::scripts(ctx);
    let w = sc.way(way_name(way)).ok_or_else(|| format!("no way of speaking called `{way}`"))?;
    let Some(me) = ctx.db.character().id().find(speaker) else { return Err("no speaker".into()) };
    // The `#<id>` handles a mind is shown people by are not words anyone hears: each is said as
    // the speaker refers to that one (a name it knows, "that stranger"; a far figure's handle as
    // the one it saw). An id that names no one is left as written.
    let written: String = text.chars().take(w.max_chars).collect();
    let text = living_rules::normalize::spoken_without_ids(text, |id| {
        let real = crate::far::resolve(ctx, speaker, id);
        if real == 0 || ctx.db.character().id().find(real).is_none() {
            None
        } else if real == speaker {
            Some(me.name.clone())
        } else {
            Some(common::label_for(ctx, &me, real))
        }
    });
    let text: String = text.chars().take(w.max_chars).collect();
    let Some(b) = ctx.db.body().id().find(speaker) else { return Err("no body".into()) };
    // A line to a figure the speaker's mind names by its sighting's handle (far-handle).
    let to = crate::far::resolve(ctx, speaker, to);
    let st = ctx.db.mind_state().id().find(speaker);
    if st.as_ref().is_some_and(|st| now.saturating_sub(st.spoke_ms) < SPEAK_GAP_MS) {
        return Err("speaking too fast".into());
    }
    let at = pos(&b, now);
    let world = common::world(ctx);
    // The way's refusals, in the script's words (`<way>_check`).
    way_check(ctx, &sc, w, speaker, to, &text, now)?;
    // What the spec requires, kept even by a check that forgets it (the install tries every
    // check against its spec, so this is not reached by a script that passed it).
    if w.to == To::Required && to == 0 {
        return Err(format!("the rules' {}_check let through a line to no one", w.name));
    }
    if let Some(mut st) = st {
        st.spoke_ms = now;
        ctx.db.mind_state().id().update(st);
    }
    // Saying nearly the same thing again is still spoken and heard; the speaker notices it
    // (feedback, not suppression).
    let echo = said_recently(ctx, speaker, &text, now);
    let to_name = if to != 0 { common::name_of(ctx, to) } else { String::new() };
    let how = if w.name == SAY { String::new() } else { format!(" ({})", w.name) };
    let line = if to != 0 { format!("{}{how} to {}: “{}”", me.name, to_name, text) } else { format!("{}{how}: “{}”", me.name, text) };
    common::chronicle(ctx, now, "speech", speaker, to, at, line);
    // Every speaker perceives its own words, whoever controls it: a person's become lived
    // memory (docs/PLAYER_MEMORY.md), a mind's are in its experience like anyone's.
    let said = format!("{}: “{}”", fill(ctx, if to != 0 { &w.said_to } else { &w.said }, &me, speaker, to, 0.0), text);
    let said_id = percept(ctx, &me, now, "said", speaker, to, at, said, 0.5);
    // A line whose ids were said as words: the speaker keeps what it wrote beside what was said
    // (`spoken_as`; a mind journals it, trials.py counts them), and hearers get only the words.
    if written != text {
        percept(ctx, &me, now, "spoken_as", speaker, to, at, format!("Your line was said as “{text}”: you wrote “{written}”, and #ids are not words anyone hears."), 0.2);
    }
    if let Some((ago_s, said)) = echo {
        let when = if ago_s < 5 { "just now".to_string() } else { format!("{ago_s} s ago") };
        percept(ctx, &me, now, "repeat", speaker, to, at, format!("You said almost the same thing {when}: “{said}”."), 0.3);
    }
    // Listeners, gathered once within the way's widest carry: each then hears as far as its own
    // senses reach (and the way carries). Animals hear a voice, not words.
    let near: Vec<(Character, f32, (f32, f32))> = common::creatures_near(ctx, at, w.widest(common::widest_hearing(ctx)), now)
        .into_iter()
        .filter(|c| c.id != speaker)
        .filter_map(|c| ctx.db.character().id().find(c.id).map(|ch| (ch, c.dist, c.pos)))
        .collect();
    let carries = |id: u32, d: f32| d <= w.carry_for(common::hearing_for(ctx, id, &world, now));
    if !w.animals.is_empty() {
        for (c, _, p) in near.iter().filter(|(c, d, _)| &*c.kind != "person" && !common::instinct_only(ctx, c) && carries(c.id, *d)) {
            percept(ctx, c, now, "signal", speaker, 0, at, format!("You hear {}, {}.", w.animals, direction(*p, at)), 0.25);
        }
    }
    let hearers: Vec<&(Character, f32, (f32, f32))> = near.iter().filter(|(c, d, _)| &*c.kind == "person" && (!w.only_to || c.id == to) && carries(c.id, *d)).collect();
    // Silence is information: a line to someone who did not receive the words, or to the room
    // when no one did. The speaker is told the fact (`speech_truth`): they could not have heard
    // it, never a "No answer" that reads as a refusal, and no advice (what to do about it is the
    // mind's or the player's choice; the ways' reach is in the world text). Decided from the same
    // `hearers` the line's `audience` row lists (what `LIVING_GREET=nearest` reads).
    let laws = common::laws(ctx);
    let unheard = if to != 0 && !hearers.iter().any(|(c, _, _)| c.id == to) {
        Some(unheard_text(ctx, &sc, w, &me, to, at, common::facing_at(&b, now), laws.speech_truth, now))
    } else if to == 0 && hearers.is_empty() && laws.speech_truth {
        // A line to the room that no one received: the speaker learns that too.
        Some(NOBODY_HEARD.to_string())
    } else {
        None
    };
    if let Some(text) = unheard {
        let line = percept(ctx, &me, now, "silence", to, speaker, at, text.clone(), 0.35);
        // A person playing the speaker gets the same words as an outcome of what they said.
        if let (true, Some(line)) = (laws.speech_truth, line) {
            let what = if to != 0 { format!("{} to {}", w.label.to_lowercase(), common::label_for(ctx, &me, to)) } else { w.label.to_lowercase() };
            crate::outcomes::write(ctx, speaker, line, now, &crate::outcomes::Told { kind: kind::ACT, ok: false, skill: &w.name, code: code::REACH, what: &what, why: &text, other: to }, false);
        }
    }
    let address = laws.address_m;
    let close = hearers.iter().filter(|(_, d, _)| *d <= address).count();
    // How a line to the room was said (speech-address): whom it names, and whom its
    // speaker was talking with (the conversation state the 60 s rule reads: a line between the
    // speaker and another within the last minute). The same fact for every hearer, in each
    // hearer's own labels (`room_address`); none for a line to someone.
    // Whom the line names among those near: by name, or by a kin word for what they are to the
    // speaker ("Mother" said by her child; the world's `kin_terms()`, talk-turns), in the line's
    // order, the speaker left out, and for a line to someone the addressee too (named already).
    let naming: Vec<u32> = {
        let mut n: Vec<(usize, u32)> = near
            .iter()
            .filter(|(c, _, _)| &*c.kind == "person" && c.id != speaker && c.id != to)
            .filter_map(|(c, _, _)| named_at(ctx, &sc, &me, &text, c).map(|i| (i, c.id)))
            .collect();
        n.sort_unstable();
        n.into_iter().map(|(_, id)| id).collect()
    };
    let partner = if to == 0 { talking_with(ctx, &sc, speaker, now).filter(|p| !naming.contains(p)) } else { None };
    // The words for listener `c` at `d` metres, in its terms, with how a line to the room was
    // said in its own labels: as heard awake, as told on waking, and as what woke a sleeper.
    let heard_text = |c: &Character, d: f32| {
        let template = if to == c.id { &w.heard_to_you } else if to != 0 { &w.heard_to } else { &w.heard };
        let filled = fill(ctx, template, c, speaker, to, d);
        if to == 0 {
            format!("{}: “{}”", place_how(&filled, &room_address(ctx, c, &naming, partner)), text)
        } else if naming.is_empty() {
            format!("{}: “{}”", place_how(&filled, ""), text)
        } else {
            // A line to someone that names others: "Sissly Fenner said to a stranger, naming you".
            format!("{}, naming {}: “{}”", place_how(&filled, ""), named_words(ctx, c, &naming), text)
        }
    };
    // A sleeper the words reach wakes if the line is loud and near enough (the way's
    // `loudness`, `perceive::wakes`), and hears it awake; any other keeps it for its waking
    // (`perceive::heard_asleep`), whoever plays it: no conversation turn, no name learnt, not
    // among the line's audience or those who heard it, until then.
    let asleep: Vec<u32> = hearers
        .iter()
        .filter(|(c, _, _)| crate::perceive::asleep(ctx, c.id))
        .filter_map(|(c, d, _)| {
            if crate::perceive::wakes(ctx, *d, w.loudness) {
                crate::perceive::request_waking(ctx, c.id, &heard_text(c, *d), now, crate::perceive::Wake::Sound);
                None
            } else {
                Some(c.id)
            }
        })
        .collect();
    // Who received the words and how they stood toward the speaker, for the minds' turn-taking
    // (`LIVING_GREET`): one `audience` row per line, where the world keeps it (`speech_audience`).
    if laws.speech_audience {
        let face = common::heading_at(&b, now);
        let people: Vec<Hearer> = hearers
            .iter()
            .filter(|(c, _, _)| !asleep.contains(&c.id))
            .map(|(c, d, p)| Hearer { id: c.id, d: *d, off: if *d < 0.01 { 0.0 } else { living_rules::steer::wrap((p.1 - at.1).atan2(p.0 - at.0) - face).abs() } })
            .collect();
        for old in ctx.db.audience().at_ms().filter(..now.saturating_sub(AUDIENCE_KEEP_MS)).map(|a| a.id).collect::<Vec<_>>() {
            ctx.db.audience().id().delete(old);
        }
        ctx.db.audience().insert(Audience { id: 0, speaker, to, at_ms: now, hearers: people });
    }
    // Saying one's own name tells it to everyone who receives the words (an introduction).
    let introduces = w.introduces && mentions(&text, &me.name);
    // Words to someone that hold their name tell it to those who receive them and see whom it
    // was for (overheard names): never from closeness, never from a whisper (`names`).
    let addressee = (to != 0 && w.names).then(|| ctx.db.character().id().find(to)).flatten().filter(|t| t.kind == "person" && mentions(&text, &t.name));
    let addressee_at = addressee.as_ref().and_then(|t| ctx.db.body().id().find(t.id)).map(|tb| pos(&tb, now));
    let map = common::map(ctx);
    // Whether creature `id`, standing at `eye`, sees `target` at `p` (the one sight rule, with
    // its facing when the world's law gives it a field).
    let sees = |id: u32, eye: (f32, f32), target: u32, p: (f32, f32)| {
        ctx.db.body().id().find(id).is_some_and(|ob| crate::perception::in_sight(ctx, &map, id, eye, common::facing_at(&ob, now), target, p, common::dist(eye, p), &world, now, false))
    };
    for (c, d, p) in hearers.iter().copied() {
        if asleep.contains(&c.id) {
            let addressed = to == c.id || (to == 0 && (close == 1 && *d <= address || naming.contains(&c.id)));
            crate::perceive::heard_asleep(ctx, c, speaker, to, at, &heard_text(c, *d), if addressed { w.addressed } else { w.overheard }, now);
            continue;
        }
        let news = introduces && crate::perception::introduce(ctx, c.id, speaker, now);
        let addressed = to == c.id || (to == 0 && (close == 1 && *d <= address || naming.contains(&c.id)));
        let heard = heard_text(c, *d);
        percept(ctx, c, now, &w.kind, speaker, to, at, heard, if addressed { w.addressed } else { w.overheard });
        // A name that is news is a moment of its own (below the 0.6 that wakes a body's graph, so
        // learning a name never re-runs what the listener is doing).
        if news {
            percept(ctx, c, now, "introduced", speaker, 0, at, format!("{} told you their name.", common::label_cap(ctx, c, speaker)), 0.55);
        }
        if let (Some(t), Some(tp)) = (&addressee, addressee_at) {
            if c.id != t.id && sees(c.id, *p, t.id, tp) && crate::perception::introduce(ctx, c.id, t.id, now) {
                let caller = common::label_for(ctx, c, speaker);
                percept(ctx, c, now, "introduced", t.id, speaker, tp, format!("You heard {caller} call {} by name.", t.name), 0.55);
            }
        }
        if let Some(mut st) = ctx.db.mind_state().id().find(c.id) {
            st.heard_ms = now;
            st.speaker = speaker;
            ctx.db.mind_state().id().update(st);
        }
        // Whether and how to answer is the listener's mind's affair: its service sees this
        // experience and gives the listener a conversation turn. Speech no longer requests a
        // full deliberation.
    }
    // Those who learn only that something was said, between whom (a whisper's onlookers): no
    // words, no name.
    if let Some(n) = &w.noticed {
        for (c, dist, p) in near.iter().filter(|(c, d, _)| &*c.kind == "person" && *d <= n.within_m && c.id != to && !hearers.iter().any(|(h, _, _)| h.id == c.id)) {
            if n.seen && !sees(c.id, *p, speaker, at) {
                continue;
            }
            percept(ctx, c, now, &n.kind, speaker, to, at, fill(ctx, &n.text, c, speaker, to, *dist), n.salience);
        }
    }
    // Who heard: those who received the words and whom the speaker saw (the sight rule), with
    // the line, in this transaction.
    if let Some(line) = said_id {
        let mut seen: Vec<(f32, u32)> = hearers
            .iter()
            .filter(|(c, _, _)| !asleep.contains(&c.id))
            .filter(|(c, d, p)| crate::perception::in_sight(ctx, &map, speaker, at, common::facing_at(&b, now), c.id, *p, *d, &world, now, false))
            .map(|(c, d, _)| (*d, c.id))
            .collect();
        seen.sort_by(|a, b| a.0.total_cmp(&b.0));
        // A mind's speaker knows a hearer it cannot make out by its sighting's handle (far-handle).
        let mind = crate::combat::human(ctx, speaker).is_none();
        let hearers: Vec<u32> = seen
            .into_iter()
            .map(|(_, id)| match ctx.db.character().id().find(id).filter(|_| mind) {
                Some(t) => crate::far::id_for(ctx, &me, &t, now),
                None => id,
            })
            .collect();
        ctx.db.line_heard().insert(LineHeard { line, speaker, way: w.name.clone(), hearers, at_ms: now });
    }
    Ok(())
}

/// What a speaker is told of a line to the room that no one received (`speech_truth`).
pub const NOBODY_HEARD: &str = "Nobody was near enough to hear you.";

/// What a speaker is told when `to` did not receive its words in way `w`. With `truth` (the
/// `speech_truth` law, on by default) the fact alone: "<Who> is too far away: they could not
/// have heard you." when the speaker sees them, "<Who> is out of earshot: they could not have
/// heard you." when it does not (out of sight, absent or dead alike, so ids cannot be probed).
/// Someone too far away to make out is "They are …" (`unheard_subject`). No advice: what to do
/// about it is the speaker's choice. Without it, `speech-2`'s words.
#[allow(clippy::too_many_arguments)]
fn unheard_text(ctx: &ReducerContext, sc: &living_rules::script::Scripts, w: &WaySpec, me: &Character, to: u32, at: (f32, f32), facing: f32, truth: bool, now: u64) -> String {
    let world = common::world(ctx);
    let seen = ctx.db.character().id().find(to).filter(|c| c.alive).and_then(|_| ctx.db.body().id().find(to)).is_some_and(|tb| {
        let p = pos(&tb, now);
        crate::perception::in_sight(ctx, &common::map(ctx), me.id, at, facing, to, p, common::dist(at, p), &world, now, false)
    });
    let who = unheard_subject(&common::label_cap(ctx, me, to));
    match (truth, seen) {
        (true, true) => format!("{who} too far away: they could not have heard you."),
        (true, false) => format!("{who} out of earshot: they could not have heard you."),
        (false, true) => {
            let louder = sc.ways().iter().filter(|o| o.public() && o.carry_for(1.0) > w.carry_for(1.0) && o.needs.is_empty()).max_by(|a, b| a.carry_for(1.0).total_cmp(&b.carry_for(1.0)));
            let how = louder.map_or("go closer".to_string(), |o| format!("{} or go closer", o.label.to_lowercase()));
            format!("{who} too far to hear you; {how}.")
        }
        (false, false) => format!("No answer from {}; they don't seem to be within earshot.", common::label_for(ctx, me, to)),
    }
}

/// The subject of an unheard line's words: "Bram is", "A stranger is"; for someone too far away
/// to make out "They are", so the label is not followed by "is too far away" (fix-far-silence).
fn unheard_subject(label: &str) -> String {
    if label.eq_ignore_ascii_case(living_rules::script::FAR_PERSON) {
        "They are".into()
    } else {
        format!("{label} is")
    }
}

/// Whether `to` would receive the words of a line in way `w` that `speaker`, standing at `at`,
/// says now: a living person within what the way carries for their own hearing (the rule
/// [`speak`] gives the words by).
pub fn within_reach(ctx: &ReducerContext, w: &WaySpec, at: (f32, f32), to: u32, now: u64) -> bool {
    if !ctx.db.character().id().find(to).is_some_and(|c| c.alive && c.kind == "person") {
        return false;
    }
    let Some(tb) = ctx.db.body().id().find(to) else { return false };
    let world = common::world(ctx);
    common::dist(at, pos(&tb, now)) <= w.carry_for(common::hearing_for(ctx, to, &world, now))
}

/// A plan's queued line to `to` that came due while `to` was beyond the way's reach
/// (`speech_truth`): it is not said, and the speaker is told so in the words a spoken line
/// gets ([`unheard_text`]), with the line it kept: a `silence` row, as for a line said out of
/// earshot. `Err` when the way is unknown.
pub fn unsaid(ctx: &ReducerContext, speaker: u32, to: u32, way: &str, text: &str, now: u64) -> Result<(), String> {
    let sc = common::scripts(ctx);
    let w = sc.way(way_name(way)).ok_or_else(|| format!("no way of speaking called `{way}`"))?;
    let (Some(me), Some(b)) = (ctx.db.character().id().find(speaker), ctx.db.body().id().find(speaker)) else { return Ok(()) };
    let to = crate::far::resolve(ctx, speaker, to);
    let at = pos(&b, now);
    let why = unheard_text(ctx, &sc, w, &me, to, at, common::facing_at(&b, now), true, now);
    let text: String = text.trim().chars().take(w.max_chars).collect();
    percept(ctx, &me, now, "silence", to, speaker, at, format!("{why} You did not say your planned line: “{text}”."), 0.35);
    Ok(())
}

/// The latest line someone other than `speaker` said to `to` that `speaker` heard after
/// `since_ms` (first-sight-crowd): its experience row, the way's kind, the other speaker its
/// subject and `to` (or the handle `speaker` knows them by) its object.
pub fn addressed_by_another(ctx: &ReducerContext, speaker: u32, to: u32, since_ms: u64) -> Option<Experience> {
    let sc = common::scripts(ctx);
    let kinds: Vec<&str> = sc.ways().iter().map(|w| w.kind.as_str()).collect();
    let real = crate::far::resolve(ctx, speaker, to);
    ctx.db
        .experience()
        .observer()
        .filter(speaker)
        .filter(|e| e.at_ms > since_ms && (e.object == to || e.object == real) && e.subject != 0 && e.subject != speaker && e.subject != to && e.subject != real && kinds.contains(&e.kind.as_str()))
        .max_by_key(|e| e.at_ms)
}

/// A mind's decided line that its way refused (`mind_install_way`, a deliberation's
/// `mind_say`): not said, and told to the speaker in the rules' words: "You did not say “…”: a
/// whisper needs someone to whisper to." The same row kind as a held line (`unsaid`).
pub fn unsaid_refused(ctx: &ReducerContext, speaker: u32, to: u32, text: &str, why: &str, now: u64) {
    let (Some(me), Some(b)) = (ctx.db.character().id().find(speaker), ctx.db.body().id().find(speaker)) else { return };
    let why = why.trim().trim_end_matches('.');
    percept(ctx, &me, now, "unsaid", to, speaker, pos(&b, now), format!("You did not say “{}”: {why}.", text.trim()), 0.45);
}

/// A mind's line to `to` that comes due after the speaker heard another address them since its
/// decision (`heard_first_rethinks`, docs/FIRST_SIGHT.md "Crowds"): it is not said yet. The
/// speaker is told, with the line it heard, and its mind is asked to think again with that in
/// front of it; what it decides then is said as it decides.
pub fn held_for_another(ctx: &ReducerContext, speaker: u32, to: u32, text: &str, heard: &Experience, now: u64) {
    let (Some(me), Some(b)) = (ctx.db.character().id().find(speaker), ctx.db.body().id().find(speaker)) else { return };
    let who = common::label_for(ctx, &me, crate::far::resolve(ctx, speaker, to));
    let text = text.trim();
    let line = format!("You had not yet said “{text}” to {who} when you heard: {}", heard.text.trim());
    percept(ctx, &me, now, "unsaid", to, heard.subject, pos(&b, now), line.clone(), 0.5);
    crate::perceive::ask_again(ctx, speaker, &line, now);
}

/// The most similar line this speaker said within the last 90 s, when nearly the same
/// (word-set Jaccard >= 0.6): seconds ago and the words.
fn said_recently(ctx: &ReducerContext, speaker: u32, text: &str, now: u64) -> Option<(u64, String)> {
    said_like(ctx, speaker, None, text, now, 90_000).map(|(at, said)| (now.saturating_sub(at) / 1000, said))
}

/// How long a graph's `say` node keeps from saying again a line its speaker already said to the
/// same person (say-once).
pub const SAY_ONCE_MS: u64 = 45_000;

/// Whether `speaker` said nearly this line (the repeat match) to `to` within `SAY_ONCE_MS`
/// (say-once). Read from the chronicle, so it holds across a plan's install, which clears a say
/// node's own mark. Asked only by a mind plan's say node with an addressee: never for a line to
/// the room, a scene's or the admin's graph, a player's line, a deliberation's own or a talk turn's.
pub fn said_to_recently(ctx: &ReducerContext, speaker: u32, to: u32, text: &str, now: u64) -> bool {
    said_like(ctx, speaker, Some(to), text, now, SAY_ONCE_MS).is_some()
}

/// The latest line `speaker` said (to `to`, when given) within `within_ms` that is nearly
/// `text`: when it was said and its words.
fn said_like(ctx: &ReducerContext, speaker: u32, to: Option<u32>, text: &str, now: u64, within_ms: u64) -> Option<(u64, String)> {
    let mut latest: Option<(u64, String)> = None;
    for c in ctx.db.chronicle().at_ms().filter(now.saturating_sub(within_ms)..).filter(|c| c.kind == "speech" && c.a == speaker && to.map_or(true, |t| c.b == t)) {
        // Chronicle rows count exact repeats as "… (×n)".
        let base = c.text.rsplit_once(" (×").map_or(c.text.as_str(), |(b, _)| b);
        let said = base.split_once('“').map(|(_, t)| t.trim_end_matches('”')).unwrap_or(base);
        if nearly_same(said, text) && latest.as_ref().map_or(true, |l| c.at_ms >= l.0) {
            latest = Some((c.at_ms, said.to_string()));
        }
    }
    latest
}

/// The repeat match: word sets (words of three letters or more) with Jaccard >= 0.6, or the
/// same text when either has no such word.
fn nearly_same(a: &str, b: &str) -> bool {
    let words = |t: &str| -> std::collections::HashSet<String> { t.to_lowercase().split(|c: char| !c.is_alphanumeric()).filter(|w| w.len() > 2).map(String::from).collect() };
    let (x, y) = (words(a), words(b));
    if x.is_empty() || y.is_empty() {
        return a.trim().eq_ignore_ascii_case(b.trim());
    }
    x.intersection(&y).count() as f32 / x.union(&y).count() as f32 >= 0.6
}

/// Where in `text` a person's given name (or whole name) is said: the index of its first word, as
/// [`mentions`] finds it.
fn mention_at(text: &str, name: &str) -> Option<usize> {
    let t = text.to_lowercase();
    let words: Vec<&str> = t.split(|ch: char| !ch.is_alphanumeric()).filter(|w| !w.is_empty()).collect();
    let n = name.to_lowercase();
    let parts: Vec<&str> = n.split(|ch: char| !ch.is_alphanumeric()).filter(|w| !w.is_empty()).collect();
    let given = parts.first()?;
    words.iter().position(|w| w == given).or_else(|| (parts.len() > 1).then(|| words.windows(parts.len()).position(|win| win == parts.as_slice())).flatten())
}

/// Whom `speaker` is talking with now: the other side of its latest line to or from another
/// person within the last minute (the conversation state of the 60 s rule). A line in a way whose
/// words are for the addressee alone (a whisper) does not count, so the detail never tells a
/// hearer of a private exchange.
fn talking_with(ctx: &ReducerContext, sc: &living_rules::script::Scripts, speaker: u32, now: u64) -> Option<u32> {
    ctx.db
        .chronicle()
        .at_ms()
        .filter(now.saturating_sub(60_000)..=now)
        .filter(|c| c.kind == "speech" && ((c.a == speaker && c.b != 0 && c.b != speaker) || (c.b == speaker && c.a != speaker)))
        .filter(|c| !chronicle_way(&c.text).and_then(|w| sc.way(w)).is_some_and(|w| w.only_to))
        .max_by_key(|c| (c.at_ms, c.id))
        .map(|c| if c.a == speaker { c.b } else { c.a })
}

/// The way a chronicle speech line names: "Ilsa (whisper) to Bram: “…”" is `whisper`; a `say`
/// line names none.
fn chronicle_way(line: &str) -> Option<&str> {
    let head = line.split('“').next()?;
    let (_, rest) = head.split_once(" (")?;
    rest.split_once(')').map(|(w, _)| w)
}

/// Where the room detail goes in a filled template: at `{how}` when the way places it ("{a} calls
/// out{how} from about {d} m", with a comma when words follow it), else after the template.
fn place_how(filled: &str, how: &str) -> String {
    match filled.split_once("{how}") {
        Some((before, after)) if how.is_empty() => format!("{before}{after}"),
        Some((before, after)) if after.trim().is_empty() => format!("{before} {how}{after}"),
        Some((before, after)) => format!("{before} {how},{after}"),
        None if how.is_empty() => filled.to_string(),
        None => format!("{filled} {how}"),
    }
}

/// What `other` is to `speaker` among the relations a kin term can name (`KIN_RELATIONS`):
/// parent, child, sibling (a parent shared), grandparent, grandchild, partner (a child together).
fn kin_relations(ctx: &ReducerContext, speaker: &Character, other: &Character) -> Vec<&'static str> {
    let parents = |c: &Character| [c.parent_a, c.parent_b].into_iter().filter(|p| *p != 0).collect::<Vec<u32>>();
    let (sp, op) = (parents(speaker), parents(other));
    let grand = |c: &Character| parents(c).into_iter().filter_map(|p| ctx.db.character().id().find(p)).flat_map(|p| parents(&p)).collect::<Vec<u32>>();
    let mut out = Vec::new();
    if sp.contains(&other.id) {
        out.push("parent");
    }
    if op.contains(&speaker.id) {
        out.push("child");
    }
    if other.id != speaker.id && sp.iter().any(|p| op.contains(p)) {
        out.push("sibling");
    }
    if grand(speaker).contains(&other.id) {
        out.push("grandparent");
    }
    if grand(other).contains(&speaker.id) {
        out.push("grandchild");
    }
    let together = |a: u32, b: u32| ctx.db.character().parent_a().filter(a).any(|c| c.parent_b == b);
    if together(speaker.id, other.id) || together(other.id, speaker.id) {
        out.push("partner");
    }
    out
}

/// Where `speaker`'s line names `other`: by name (`mention_at`) or by a kin word for what they
/// are to the speaker (the world's `kin_terms()`), the earlier of the two.
fn named_at(ctx: &ReducerContext, sc: &living_rules::script::Scripts, speaker: &Character, text: &str, other: &Character) -> Option<usize> {
    let by_name = mention_at(text, &other.name);
    let rel = kin_relations(ctx, speaker, other);
    let by_kin = if rel.is_empty() { None } else { sc.kin().named_at(text, &rel) };
    match (by_name, by_kin) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    }
}

/// Those a line names, in `hearer`'s labels ("you" for the hearer): "Agnes Fenner and you".
fn named_words(ctx: &ReducerContext, hearer: &Character, naming: &[u32]) -> String {
    let labels: Vec<String> = naming.iter().map(|id| if *id == hearer.id { "you".to_string() } else { common::label_for(ctx, hearer, *id) }).collect();
    list_words(&labels)
}

/// "A, B and C", a label said again reading "another" ("a stranger and another stranger").
fn list_words(labels: &[String]) -> String {
    let mut seen: Vec<&str> = Vec::new();
    let named: Vec<String> = labels
        .iter()
        .map(|l| {
            let again = seen.contains(&l.as_str());
            seen.push(l);
            match (again, l.strip_prefix("a ").or_else(|| l.strip_prefix("an "))) {
                (true, Some(rest)) => format!("another {rest}"),
                _ => l.clone(),
            }
        })
        .collect();
    match named.as_slice() {
        [] => String::new(),
        [one] => one.clone(),
        [init @ .., last] => format!("{} and {last}", init.join(", ")),
    }
}

/// How `hearer` heard a line to the room: "to the room, naming Edda and a stranger", "to the
/// room while talking with Lorcan", both, or nothing. Everyone is named as `hearer` knows them
/// (`label_for`: a name only where known and near enough to make out; "you" for the hearer).
fn room_address(ctx: &ReducerContext, hearer: &Character, naming: &[u32], partner: Option<u32>) -> String {
    let label = |id: u32| if id == hearer.id { "you".to_string() } else { common::label_for(ctx, hearer, id) };
    address_words(&naming.iter().map(|id| label(*id)).collect::<Vec<_>>(), partner.map(label).as_deref())
}

/// The words of [`room_address`] from labels: a label said twice reads "another" the second time
/// ("a stranger and another stranger").
fn address_words(naming: &[String], partner: Option<&str>) -> String {
    let list = list_words(naming);
    match (list.is_empty(), partner) {
        (true, None) => String::new(),
        (true, Some(p)) => format!("to the room while talking with {p}"),
        (false, None) => format!("to the room, naming {list}"),
        (false, Some(p)) => format!("to the room, naming {list}, while talking with {p}"),
    }
}

/// Whether `text` names `name`: the whole name as its words in a row ("Vessa Pontil"), or its
/// first word, the given name ("Vessa"). Before `speech-2` a name of two words never matched.
fn mentions(text: &str, name: &str) -> bool {
    let t = text.to_lowercase();
    let words: Vec<&str> = t.split(|ch: char| !ch.is_alphanumeric()).filter(|w| !w.is_empty()).collect();
    let n = name.to_lowercase();
    let parts: Vec<&str> = n.split(|ch: char| !ch.is_alphanumeric()).filter(|w| !w.is_empty()).collect();
    match parts.first() {
        None => false,
        Some(given) => words.iter().any(|w| w == given) || (parts.len() > 1 && words.windows(parts.len()).any(|win| win == parts.as_slice())),
    }
}

#[cfg(test)]
mod tests {
    use super::mentions;

    #[test]
    fn a_line_to_the_room_says_whom_it_calls_and_whom_its_speaker_talks_with() {
        let s = |v: &[&str]| v.iter().map(|x| x.to_string()).collect::<Vec<_>>();
        assert_eq!(super::address_words(&s(&["Edda Hollin", "Ife Okoro"]), None), "to the room, naming Edda Hollin and Ife Okoro");
        assert_eq!(super::address_words(&s(&["a stranger", "Ife Okoro"]), None), "to the room, naming a stranger and Ife Okoro");
        assert_eq!(super::address_words(&s(&["a stranger", "a stranger"]), None), "to the room, naming a stranger and another stranger");
        assert_eq!(super::address_words(&[], Some("Lorcan Vane")), "to the room while talking with Lorcan Vane");
        assert_eq!(super::address_words(&s(&["you"]), Some("someone too far away to make out")), "to the room, naming you, while talking with someone too far away to make out");
        assert_eq!(super::address_words(&[], None), "");
        assert_eq!(super::place_how("A stranger said", "to the room, naming Ife Okoro"), "A stranger said to the room, naming Ife Okoro");
        assert_eq!(super::place_how("A stranger calls out{how} from about 20 m", "to the room while talking with you"), "A stranger calls out to the room while talking with you, from about 20 m");
        assert_eq!(super::place_how("A stranger calls out{how} from about 20 m", ""), "A stranger calls out from about 20 m");
        assert_eq!(super::chronicle_way("Ilsa (whisper) to Bram: “a (b) c”"), Some("whisper"));
        assert_eq!(super::chronicle_way("Ilsa to Bram: “a (b) c”"), None);
        assert_eq!(super::mention_at("Lumi! I heard you. And Ife, you're on my side", "Ife Okoro"), Some(5));
        assert_eq!(super::mention_at("Nothing here", "Ife Okoro"), None);
    }

    #[test]
    fn the_repeat_match_is_nearly_the_same_words() {
        let a = "Aldous — stay a moment, close, where I can see your face. I've tried three times to say this.";
        assert!(super::nearly_same(a, a));
        assert!(super::nearly_same(a, "Aldous, stay a moment close, where I can see your face. I have tried three times to say this."));
        assert!(!super::nearly_same(a, "Has anyone seen the cart?"));
        assert!(super::nearly_same("Hi!", "hi!"), "no long words: the same text");
        assert!(!super::nearly_same("Hi!", "Yo!"));
    }

    #[test]
    fn a_list_of_named_reads_another_for_a_label_said_twice() {
        let s = |v: &[&str]| v.iter().map(|x| x.to_string()).collect::<Vec<_>>();
        assert_eq!(super::list_words(&s(&["Agnes Fenner"])), "Agnes Fenner");
        assert_eq!(super::list_words(&s(&["a stranger", "a stranger", "you"])), "a stranger, another stranger and you");
        assert_eq!(super::place_how("Sissly Fenner said to a stranger", ""), "Sissly Fenner said to a stranger");
    }

    #[test]
    fn a_far_figure_is_they_not_the_label_twice() {
        assert_eq!(super::unheard_subject("Someone too far away to make out"), "They are");
        assert_eq!(super::unheard_subject("Bram"), "Bram is");
        assert_eq!(super::unheard_subject("A stranger"), "A stranger is");
    }

    #[test]
    fn a_name_is_mentioned_by_its_given_name_or_in_full() {
        assert!(mentions("I am Walker1, new here.", "Walker1"));
        assert!(mentions("I'm Vessa.", "Vessa Pontil"));
        assert!(mentions("Vessa Pontil, at your service.", "Vessa Pontil"));
        assert!(!mentions("I'm Pontil's cousin.", "Vessa Pontil"));
        assert!(!mentions("Vessage for you.", "Vessa Pontil"));
        assert!(!mentions("Hello.", ""));
    }
}

/// A speaker's lines left its window (trimmed or consolidated): their `heard` rows go too.
pub fn forget_line(ctx: &ReducerContext, line: u64) {
    ctx.db.line_heard().line().delete(line);
}

/// Rewrite `speech_card` from a skill script: one row per way of speaking. Rows of ways the
/// script no longer has go.
pub fn cards(ctx: &ReducerContext, sc: &living_rules::script::Scripts) {
    for old in ctx.db.speech_card().iter().filter(|c| sc.way(&c.name).is_none()).map(|c| c.name).collect::<Vec<_>>() {
        ctx.db.speech_card().name().delete(old);
    }
    for w in sc.ways() {
        let card = SpeechCard {
            name: w.name.clone(),
            label: w.label.clone(),
            order: w.order,
            about: w.about.clone(),
            needs_to: w.to == To::Required,
            reach_m: w.reach,
            carry_m: w.carry_for(sc.reach().hearing),
            requires: w.needs.clone(),
            needs_sight: w.needs_sight,
            private: w.only_to,
            max_chars: w.max_chars as u16,
            gap_ms: ((w.gap_s * 1000.0) as u64).max(SPEAK_GAP_MS) as u32,
        };
        if ctx.db.speech_card().name().find(card.name.clone()).is_some() {
            ctx.db.speech_card().name().update(card);
        } else {
            ctx.db.speech_card().insert(card);
        }
    }
}

/// Who heard my current character's own lines (its `heard` rows, joined to `my_experience` by
/// `line` = the `said` row's id). One point lookup on `heard.speaker`: it re-runs only when my
/// own lines are heard or leave my window, never on anyone else's speech.
#[spacetimedb::view(accessor = my_heard, public, primary_key = line)]
pub fn my_heard(ctx: &ViewContext) -> Vec<LineHeard> {
    crate::perception::current(ctx).map(|c| ctx.db.line_heard().speaker().filter(c.id).collect()).unwrap_or_default()
}
