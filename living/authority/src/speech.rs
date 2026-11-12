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
    let text: String = text.chars().take(w.max_chars).collect();
    let Some(me) = ctx.db.character().id().find(speaker) else { return Err("no speaker".into()) };
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
    let (naming, partner) = if to == 0 {
        let mut naming: Vec<(usize, u32)> = near
            .iter()
            .filter(|(c, _, _)| &*c.kind == "person" && c.id != speaker)
            .filter_map(|(c, _, _)| mention_at(&text, &c.name).map(|i| (i, c.id)))
            .collect();
        naming.sort_unstable();
        let naming: Vec<u32> = naming.into_iter().map(|(_, id)| id).collect();
        (naming.clone(), talking_with(ctx, &sc, speaker, now).filter(|p| !naming.contains(p)))
    } else {
        (Vec::new(), None)
    };
    // The words for listener `c` at `d` metres, in its terms, with how a line to the room was
    // said in its own labels: as heard awake, as told on waking, and as what woke a sleeper.
    let heard_text = |c: &Character, d: f32| {
        let template = if to == c.id { &w.heard_to_you } else if to != 0 { &w.heard_to } else { &w.heard };
        let how = if to == 0 { room_address(ctx, c, &naming, partner) } else { String::new() };
        format!("{}: “{}”", place_how(&fill(ctx, template, c, speaker, to, d), &how), text)
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
            let addressed = to == c.id || (to == 0 && (close == 1 && *d <= address || mentions(&text, &c.name)));
            crate::perceive::heard_asleep(ctx, c, speaker, to, at, &heard_text(c, *d), if addressed { w.addressed } else { w.overheard }, now);
            continue;
        }
        let news = introduces && crate::perception::introduce(ctx, c.id, speaker, now);
        let addressed = to == c.id || (to == 0 && (close == 1 && *d <= address || mentions(&text, &c.name)));
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

/// The most similar line this speaker said within the last 90 s, when nearly the same
/// (word-set Jaccard >= 0.6): seconds ago and the words.
fn said_recently(ctx: &ReducerContext, speaker: u32, text: &str, now: u64) -> Option<(u64, String)> {
    let words = |t: &str| -> std::collections::HashSet<String> {
        t.to_lowercase().split(|c: char| !c.is_alphanumeric()).filter(|w| w.len() > 2).map(String::from).collect()
    };
    let mine = words(text);
    let mut latest: Option<(u64, String)> = None;
    for c in ctx.db.chronicle().at_ms().filter(now.saturating_sub(90_000)..).filter(|c| c.kind == "speech" && c.a == speaker) {
        // Chronicle rows count exact repeats as "… (×n)".
        let base = c.text.rsplit_once(" (×").map_or(c.text.as_str(), |(b, _)| b);
        let said = base.split_once('“').map(|(_, t)| t.trim_end_matches('”')).unwrap_or(base);
        let theirs = words(said);
        let same = if mine.is_empty() || theirs.is_empty() {
            said.trim().eq_ignore_ascii_case(text.trim())
        } else {
            mine.intersection(&theirs).count() as f32 / mine.union(&theirs).count() as f32 >= 0.6
        };
        if same && latest.as_ref().map_or(true, |l| c.at_ms >= l.0) {
            latest = Some((c.at_ms, said.to_string()));
        }
    }
    latest.map(|(at, said)| (now.saturating_sub(at) / 1000, said))
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
    let mut seen: Vec<&str> = Vec::new();
    let named: Vec<String> = naming
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
    let list = match named.as_slice() {
        [] => String::new(),
        [one] => one.clone(),
        [init @ .., last] => format!("{} and {last}", init.join(", ")),
    };
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
