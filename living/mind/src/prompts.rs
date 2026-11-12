//! Prompt construction. Context is assembled only from the character's own persona,
//! relations, beliefs, judgments, places, episodes and the scene it currently perceives.

use std::sync::Arc;

#[derive(Clone, Copy)]
enum Stability {
    Shared,
    Character,
    Dynamic,
}

#[derive(Default)]
pub struct Segments {
    shared: String,
    character: String,
    dynamic: String,
}

impl Segments {
    fn push(&mut self, stability: Stability, text: impl AsRef<str>) {
        let out = match stability {
            Stability::Shared => &mut self.shared,
            Stability::Character => &mut self.character,
            Stability::Dynamic => &mut self.dynamic,
        };
        out.push_str(text.as_ref());
    }

    fn render(mut self) -> String {
        self.shared.push_str(&self.character);
        self.shared.push_str(&self.dynamic);
        self.shared
    }
}

fn shared(text: impl AsRef<str>) -> String {
    let mut out = Segments::default();
    out.push(Stability::Shared, text);
    out.render()
}

/// The world's own sections of the rules text, from its seed: the WORLD line, its seasons and its
/// people's life table. The rest is the world's rule script's (`Scripts::world_text`, built
/// from each law's description), so what minds are told follows the rules.
static WORLD_PARTS: std::sync::OnceLock<(String, String, String)> = std::sync::OnceLock::new();
/// The rules text for the rules revision it was built from.
static RULES_TEXT: std::sync::RwLock<Option<(u32, Arc<str>)>> = std::sync::RwLock::new(None);

/// The judgments a graph may read (`judged`), when they are refreshed (mind/judge.rs).
static JUDGED: std::sync::OnceLock<String> = std::sync::OnceLock::new();

pub fn set_judgments(grammar: String) {
    let _ = JUDGED.set(grammar);
}

fn judged_line() -> String {
    JUDGED.get().filter(|g| !g.is_empty()).map(|g| format!("\n  Judgments of your own, refreshed in the background while you fight (false while there is none, or add \"else\": true): {g}")).unwrap_or_default()
}

/// How a person's system prompts frame the model (`LIVING_FRAME`, experiment `exp-player-frame`).
/// `character` (the default) leaves every prompt as it was: the model is the person. `player`
/// opens deliberation, compiling, consolidation and conversation turns with `PLAYER_FRAME`: the
/// model is an AI playing the person in a world shared with other players. Only the opening
/// sentence differs (test `player_frame_changes_only_the_opening`); everything shared stays one
/// cacheable prefix. Animals, identities, sleep and player memory are not framed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Frame {
    Character,
    Player,
}

impl Frame {
    pub fn parse(v: Option<&str>) -> Result<Frame, String> {
        match v.map(str::trim) {
            None | Some("") | Some("character") => Ok(Frame::Character),
            Some("player") => Ok(Frame::Player),
            Some(other) => Err(format!("LIVING_FRAME={other}: expected character or player")),
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Frame::Character => "character",
            Frame::Player => "player",
        }
    }
}

static FRAME: std::sync::OnceLock<Frame> = std::sync::OnceLock::new();

/// The frame this service runs under, read once from `LIVING_FRAME` (main checks it at start).
pub fn frame() -> Frame {
    *FRAME.get_or_init(|| Frame::parse(std::env::var("LIVING_FRAME").ok().as_deref()).unwrap_or(Frame::Character))
}

/// The player frame's shared opening. Kept short and neutral: no goals, activities or advice.
pub const PLAYER_FRAME: &str = "You are an AI playing the person described under # Who you are, in a persistent world shared with other players, human and AI. \
For you, as for every player, the person's body, needs and death are real, and the world's rules hold. \
What you pursue in this life is your own choice. \
Whatever the person says or writes is in their own words, inside the world: never speak out of character.";

/// Each framed prompt's opening sentence as it has always read (the `character` frame).
const THINK_OPENING: &str = "You are the mind of the person described under # Who you are, living in a persistent simulated world.";
const CONSOLIDATE_OPENING: &str = "You are the memory and self-understanding of the person described under # Who you are, in a persistent simulated world.";
const TALK_OPENING: &str = "You are the person described under # Who you are, living in a persistent world, face to face with the other person described below.";

/// The opening sentence of a framed prompt.
fn opening(frame: Frame, character: &'static str) -> String {
    match frame {
        Frame::Character => character.to_string(),
        Frame::Player => {
            let role = match character {
                THINK_OPENING => "Here you are that person's mind.",
                CONSOLIDATE_OPENING => "Here you are that person's memory and self-understanding, kept in their own terms.",
                _ => "Here you are that person, face to face with the other person described below.",
            };
            format!("{PLAYER_FRAME} {role}")
        }
    }
}

/// The revision of the world's rule script last read.
static RULES_REV: std::sync::RwLock<Option<u32>> = std::sync::RwLock::new(None);
/// Its source, for laws the mind service asks itself (`record_text`), compiled once per thread.
static RULES_SOURCE: std::sync::RwLock<Option<(u32, Arc<String>)>> = std::sync::RwLock::new(None);

thread_local! {
    static COMPILED: std::cell::RefCell<Option<(u32, Arc<living_rules::script::Scripts>)>> = const { std::cell::RefCell::new(None) };
}

/// The world's rules compiled on this thread (the bundled rules until the world's are read).
fn compiled() -> Option<Arc<living_rules::script::Scripts>> {
    let (rev, src) = RULES_SOURCE.read().unwrap().clone().unwrap_or_else(|| (0, Arc::new(include_str!("../../scripts/skills.rhai").to_string())));
    COMPILED.with(|c| {
        if let Some((r, s)) = c.borrow().as_ref() {
            if *r == rev {
                return Some(s.clone());
            }
        }
        let s = Arc::new(living_rules::script::Scripts::with_day(&src, day_ms()).ok()?);
        *c.borrow_mut() = Some((rev, s.clone()));
        Some(s)
    })
}

/// How far an ordinary voice (`say`) carries for a person with the world's hearing (metres).
pub fn voice_m() -> f32 {
    compiled().and_then(|s| s.way("say").map(|w| w.carry_for(s.reach().hearing))).unwrap_or(9.0)
}

/// Whether the world's `cues_on` law holds (docs/ATTENTION.md): minds are asked what should
/// bring them to think, and the authority watches for it.
pub fn cues_on() -> bool {
    compiled().is_some_and(|s| s.laws().cues_on)
}

/// Whether the world's rules tell a speaker the truth about a line no one addressed could hear
/// (the `speech_truth` law; on in the bundled rules).
pub fn speech_truth() -> bool {
    compiled().map_or(true, |s| s.laws().speech_truth)
}

/// The ways of speaking for a talk turn's reply, when the world has more than `say`: each with
/// its reach in metres, from its spec and the world's hearing (`WaySpec::reach_words`).
fn ways_text() -> String {
    let Some(s) = compiled() else { return String::new() };
    if s.ways().len() < 2 {
        return String::new();
    }
    let names: Vec<String> = s.ways().iter().map(|w| format!("\"{}\"", w.name)).collect();
    let hearing = s.reach().hearing;
    let about: Vec<String> = s.ways().iter().map(|w| format!("{} ({}) = {}", w.name, w.reach_words(hearing), w.about.trim())).collect();
    format!("\"way\": how you say it, {} (default \"say\"; {}), ", names.join(" or "), about.join(" "))
}

/// A decision's line may name its way (mind-say-way): the field in the think reply's `say`,
/// naming the world's ways (the world text's SPEAKING section says what each is and how far it
/// carries), when it has more than `say`. Nothing about when to use one.
fn say_way_field() -> String {
    let names = ways();
    if names.len() < 2 {
        return String::new();
    }
    let quoted: Vec<String> = names.iter().map(|w| format!("\"{w}\"")).collect();
    format!(", \"way\": {} (optional; default \"say\")", quoted.join(" or "))
}

/// The ways of speaking the world's rules have (`<way>_speech()`), in their order.
pub fn ways() -> Vec<String> {
    compiled().map(|s| s.ways().iter().map(|w| w.name.clone()).collect()).unwrap_or_else(|| vec!["say".into()])
}

/// How a party reads one of its records, in the world's rules' words (`{id:N}` still to be
/// named as the reader knows N).
pub fn record_text(r: &living_rules::records::RecordFacts) -> Option<String> {
    compiled()?.record_text(r)
}

/// The acts a conversation turn's examples show (`talk_system`); every one must appear there as
/// `"do": "<name>"`, or the turn neither shows nor lists it (test `talk_examples_show_every_shown_act`).
const TALK_SHOWN: [&str; 7] = ["conceive", "accept", "decline", "give", "offer", "teach", "host"];

/// The acts a conversation turn may carry that the rules mark for it (`talk` in a skill's
/// spec) and the turn's examples do not show already, one line each.
pub fn talk_acts() -> String {
    living_rules::catalog::skills().iter().filter(|s| s.talk && !TALK_SHOWN.contains(&s.name.as_str())).map(living_rules::catalog::skill_line).collect::<Vec<_>>().join("\n")
}

/// The world's day in real milliseconds (its `world` row; the shipped 12 minutes until read).
/// The rules read it for laws written per game hour and for the calendar's words. It is set when
/// the world is created and never changes after, so a rules revision's text holds it.
static DAY_MS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(living_rules::DEFAULT_DAY_MS);

pub fn set_day_ms(day_ms: u64) {
    DAY_MS.store(day_ms.max(1), std::sync::atomic::Ordering::Relaxed);
}

fn day_ms() -> u64 {
    DAY_MS.load(std::sync::atomic::Ordering::Relaxed)
}

/// What each combat skill is under the world's rule script (`<skill>_combat()`): which skills
/// are real-time behavior rather than acts.
static SHAPES: std::sync::RwLock<Option<Arc<living_rules::combat::Shapes>>> = std::sync::RwLock::new(None);

/// Read the world's skills (what each is, takes and gives) and what each combat skill is from
/// the world's rule script (once per revision).
pub fn set_rules(revision: u32, source: &str) {
    if *RULES_REV.read().unwrap() == Some(revision) {
        return;
    }
    match living_rules::script::Scripts::with_day(source, day_ms()) {
        Ok(s) => {
            log::info!("rules revision {revision}: {} skills", s.skills().len());
            living_rules::catalog::set_skills(s.skills().clone());
            *RULES_REV.write().unwrap() = Some(revision);
            *RULES_SOURCE.write().unwrap() = Some((revision, Arc::new(source.to_string())));
            *SHAPES.write().unwrap() = Some(Arc::new(s.shapes().clone()));
            *TIMINGS.write().unwrap() = Some(Arc::new(timings_of(&s)));
        }
        Err(e) => log::warn!("rules revision {revision} unreadable: {e}"),
    }
}

/// The world's combat shapes (the bundled rules' until the world's have been read).
pub fn shapes() -> Arc<living_rules::combat::Shapes> {
    if let Some(s) = SHAPES.read().unwrap().as_ref() {
        return s.clone();
    }
    let bundled = Arc::new(living_rules::script::Scripts::new(include_str!("../../scripts/skills.rhai")).map(|s| s.shapes().clone()).unwrap_or_default());
    SHAPES.write().unwrap().get_or_insert(bundled).clone()
}

/// Each combat skill's timing in words (`Scripts::timing`: the numbers `skill_card` shows).
static TIMINGS: std::sync::RwLock<Option<Arc<std::collections::BTreeMap<String, String>>>> = std::sync::RwLock::new(None);

fn timings_of(s: &living_rules::script::Scripts) -> std::collections::BTreeMap<String, String> {
    // Only the skills under the combat timing model (`timed`: a windup, recovery and cooldown
    // the other side can read); the older force skills' durations are not windups.
    s.shapes().iter().filter(|(_, shape)| shape.timed).filter_map(|(skill, _)| s.timing(skill).map(|t| (skill.to_string(), t.words()))).collect()
}

/// The world's combat timings (the bundled rules' until the world's have been read).
fn timings() -> Arc<std::collections::BTreeMap<String, String>> {
    if let Some(t) = TIMINGS.read().unwrap().as_ref() {
        return t.clone();
    }
    let bundled = Arc::new(living_rules::script::Scripts::new(include_str!("../../scripts/skills.rhai")).map(|s| timings_of(&s)).unwrap_or_default());
    TIMINGS.write().unwrap().get_or_insert(bundled).clone()
}

/// Whether the skill reference states each combat skill's timing (`LIVING_SKILL_TIMINGS`, on
/// unless `0`, `off` or `false`; docs/COMBAT_MIND.md §3.7). Off, the reference is as before.
pub fn timings_on() -> bool {
    !matches!(std::env::var("LIVING_SKILL_TIMINGS").unwrap_or_default().trim().to_ascii_lowercase().as_str(), "0" | "off" | "false")
}

/// The timing of the fighting moves a character knows, for its own prompt ("# Who you are"):
/// the timed combat skills its body is offered (`ui::offered`) whose techniques it knows
/// (`<skill>_combat()`'s `knows`: the rule a player's bar shows "Unknown" by), each with its
/// timing (docs/COMBAT_MIND.md §3.7). Never another's: what an opponent's moves take is for a
/// character to learn by watching. Empty when it knows none, or with `LIVING_SKILL_TIMINGS` off.
pub fn own_timings(body: Option<&living_rules::species::Species>, knows: impl Fn(&str) -> bool) -> String {
    if !timings_on() {
        return String::new();
    }
    own_timings_of(body, knows)
}

/// `own_timings` whatever the switch says.
fn own_timings_of(body: Option<&living_rules::species::Species>, knows: impl Fn(&str) -> bool) -> String {
    let (t, shapes, skills) = (timings(), shapes(), living_rules::catalog::skills());
    let lines: Vec<String> = living_rules::ui::offered(&skills, body)
        .into_iter()
        .filter(|s| shapes.get(&s.name).is_some_and(|sh| sh.knows.iter().all(|k| knows(k))))
        .filter_map(|s| t.get(&s.name).map(|w| format!("- {}: {w}", s.name)))
        .collect();
    if lines.is_empty() {
        return String::new();
    }
    format!("\nHow long the fighting moves you know take:\n{}", lines.join("\n"))
}

/// A person's skill reference: each skill under the world's rules, with what it takes and gives.
pub fn skills_help() -> String {
    living_rules::catalog::skills_help()
}

/// A species' skill reference, with what each skill takes and gives.
pub fn species_skills_help(sp: &living_rules::species::Species) -> String {
    living_rules::species::skills_help(sp)
}
static SIZE: std::sync::OnceLock<(u32, u32)> = std::sync::OnceLock::new();

/// The world's size in tiles (from the active seed).
pub fn map_size() -> (u32, u32) {
    SIZE.get().copied().unwrap_or((96, 96))
}

/// Set once at startup from the active seed: its setting text and map size.
/// Set once at startup from the active seed: setting, map size, calendar and the people's life table.
/// The seed's calendar and the species' person life table, for the life line (`life_line`).
static LIFE: std::sync::OnceLock<(f32, f32, living_rules::life::Life)> = std::sync::OnceLock::new();

pub fn set_world(setting: &str, w: u32, h: u32, year_days: f32, pace: f32, life: living_rules::life::Life) {
    let _ = SIZE.set((w, h));
    let _ = LIFE.set((year_days, pace, life));
    let season_days = year_days / 4.0;
    // What winter does to the land is the rules' (`Scripts::seasons_words`), added per revision.
    let seasons = format!("a year is {} days — spring, summer, autumn, winter ({} each).", year_days.round(), living_rules::describe_days(season_days));
    let world = format!("WORLD: {setting} Coordinates are tiles (x east, y south, map {w}x{h}; a tile is a metre).");
    let _ = WORLD_PARTS.set((world, seasons, life_line(year_days, pace, life)));
}

/// What people are told of a person's life: the species' table under the world's `life_years`
/// law (its rules; without the law, the table as given).
fn life_line(year_days: f32, pace: f32, life: living_rules::life::Life) -> String {
    let years = |f: f32| (f * life.years).round();
    let t = living_rules::life::Pace { year_days, pace };
    format!(
        "a person lives about {} years (a year is {} days): a baby until about {}, a child until about {}, old from about {}. \
Babies cannot walk far or feed themselves; they cry when hungry, cold or alone. Children are slow, cannot build, craft or fight, and depend on others. \
Old people tire sooner and heal slower. Two adults who both choose to start a family (the act `conceive` toward each other) within two minutes, while fed, have a child about {} later.",
        life.years.round(),
        year_days.round(),
        years(life.infant),
        years(life.child),
        years(life.elder),
        living_rules::describe_days(life.gestation_days(t))
    )
}

/// The one line of "# Who you are" that says what the body is now: its age and life stage, and
/// for how long it has been in that stage, as the character row and the world's life table give
/// them (the same age and stage the scene's `you.age` carries, perceive.rs). It is a perceived
/// fact beside the persona, never part of it: a run-born adult whose identity still speaks as a
/// small child reads, every prompt, that the body is grown (docs/TRIALS.md, "Does a run-born
/// adult's identity still describe a child?"). `base` is the species' table; the world's
/// `life_years` law (Cullet's 90-year lives) is applied over it as the authority applies it.
pub fn body_line(kind: &str, stage: u8, age_days: f32, base: living_rules::life::Life, pace: living_rules::life::Pace) -> String {
    let life = compiled().map(|s| s.life(kind, base)).unwrap_or(base);
    body_line_of(kind, stage, age_days, life, pace)
}

fn body_line_of(kind: &str, stage: u8, age_days: f32, life: living_rules::life::Life, pace: living_rules::life::Pace) -> String {
    let person = kind == "person";
    let what = match (person, stage) {
        (true, 0) => "a baby",
        (true, 1) => "a child",
        (true, 3) => "old",
        (true, _) => "an adult",
        (false, 0) => "newborn",
        (false, 1) => "young",
        (false, 3) => "old",
        (false, _) => "grown",
    };
    // Where this stage began, as a fraction of the lifespan.
    let from = match stage {
        0 => 0.0,
        1 => life.infant,
        3 => life.elder,
        _ => life.child,
    };
    let year = (pace.year_days * pace.pace.max(0.0001)).max(0.0001);
    let since = (age_days - from * life.span(pace.year_days, pace.pace)).max(0.0);
    let years = (age_days / year + 1e-4).floor();
    let old = if years < 1.0 { "less than a year old".to_string() } else if years == 1.0 { "1 year old".to_string() } else { format!("{years:.0} years old") };
    // The time in a stage: in days while under a year of them, else in years.
    let how_long = if since < year {
        living_rules::describe_days(since)
    } else if since < 2.0 * year {
        "a year".to_string()
    } else {
        format!("{:.0} years", (since / year + 1e-4).floor())
    };
    format!("Your body: {old}, {what} for {how_long}.")
}

/// The world's rules as every mind is told them: the world's line, then the rule script's
/// world text with the world's seasons and life table. Built once per rules revision, so the
/// static prefix of every prompt that holds it changes only when the rules do.
pub fn world_rules() -> Arc<str> {
    let rev = RULES_SOURCE.read().unwrap().as_ref().map_or(0, |(r, _)| *r);
    if let Some((r, t)) = RULES_TEXT.read().unwrap().as_ref() {
        if *r == rev {
            return t.clone();
        }
    }
    let (world, seasons, mut life) = WORLD_PARTS.get().cloned().unwrap_or_default();
    let rules = compiled();
    // A world whose rules change people's life table tells it as its rules have it.
    if let (Some(s), Some((year_days, pace, base))) = (rules.as_ref(), LIFE.get()) {
        if s.has("life_years") {
            life = life_line(*year_days, *pace, s.life("person", *base));
        }
    }
    let text = rules.map(|s| s.world_text(&[("seasons", if seasons.is_empty() { seasons.clone() } else { format!("{seasons} {}", s.seasons_words()) }), ("life", life)])).unwrap_or_default();
    let full: Arc<str> = if world.is_empty() { text.into() } else { format!("{world}\n{text}").into() };
    *RULES_TEXT.write().unwrap() = Some((rev, full.clone()));
    full
}

/// What a graph's `relation: "stranger"` matches under the world's rules in force (the
/// `stranger_by_name` law, docs/STRANGERS.md), in the words the graph grammar gives it.
fn stranger_words() -> &'static str {
    stranger_words_for(compiled().is_some_and(|s| s.laws().stranger_by_name))
}

fn stranger_words_for(by_name: bool) -> &'static str {
    if by_name {
        "(someone whose name you do not know)"
    } else {
        "(someone you have no feelings about yet, or call a stranger)"
    }
}

pub fn grammar() -> String {
    grammar_with(&skills_help(), true)
}

/// Graph grammar for a body with the given skills (and whether it can speak).
pub fn grammar_with(skills: &str, speaks: bool) -> String {
    // People and animals get examples of their own kind of life (an animal shown a person's
    // example, like seeking the campfire when wolves are near, copies it).
    let (making, examples) = if speaks {
        (
            " \\\nThe graph is your body's real-time behavior: moving, keeping close, fleeing, fighting, eating, sleeping, keeping warm and work loops. \
Deliberate one-off interactions (starting a family, trading, giving, teaching, writing, reading, joining) are ACTS you decide in a reply (see ACTS), not graph branches.",
            "{\"if\": {\"believes\": \"wolves_near_home\", \"night\": true}, \"then\": {\"do\": \"goto\", \"target\": {\"nearest\": \"campfire\"}}} or \
{\"if\": {\"sees\": {\"nearest\": {\"kind\": \"person\", \"relation\": \"enemy\"}}}, \"then\": {\"do\": \"flee\", \"target\": {\"nearest\": {\"kind\": \"person\", \"relation\": \"enemy\"}}}}",
        )
    } else {
        (
            "",
            "{\"if\": {\"believes\": \"wolves_at_the_stream\", \"night\": true}, \"then\": {\"do\": \"flee\", \"target\": {\"nearest\": \"wolf\"}}} or \
{\"if\": {\"sees\": {\"nearest\": \"person\"}}, \"then\": {\"do\": \"flee\", \"target\": {\"nearest\": \"person\"}}}",
        )
    };
    // Only people's graphs read judgments for now (the first one is a person's fight).
    let judged = if speaks { judged_line() } else { String::new() };
    let stranger = stranger_words();
    // The world's `speech_truth`: what becomes of a planned line to someone.
    let say_note = if speaks && speech_truth() {
        " A line to someone is not said if, when it comes due, they are beyond what it carries (you are told instead) or the talk with them has moved on since you planned it (they spoke to you, or you answered them)."
    } else {
        ""
    };
    let g = format!(
        "\
BEHAVIOR GRAPH (JSON) — it runs continuously (~1 check per second, instantly on events) while you think slowly, so encode how to react, not just one action.
Nodes:
- {{\"first\": [N, ...]}} priority: every check, the first child that is running or succeeds wins; higher children interrupt lower ones. Optional label: {{\"first\": [...], \"label\": \"...\"}}.
- {{\"seq\": [N, ...]}} steps in order, remembering progress; fails when a step fails.
- {{\"if\": C, \"then\": N, \"else\": N}} guard (else optional): the branch runs only while C holds, except that work already begun under it (sleep, rest, eat, gather, build, craft, cook, teach, write, read, plant...) is finished; walking, fleeing and fighting stop as soon as C no longer holds.
- {{\"do\": \"skill\", \"target\": T, \"item\": \"...\", \"qty\": n}} perform a skill (target/item/qty only when needed); walks to the target first automatically. Add \"run\": true to run there instead (goto, follow, an attack's approach): it costs breath and is for hurry, flight and fights; out of breath you walk. A flight (flee) runs unless \"run\": false.{making}
- {{\"say\": \"<the words>\", \"to\": T}} speak (each say node speaks at most once per 45 s).{say_note}
- {{\"wait\": seconds}}
- {{\"think\": \"reason\"}} ask yourself to reconsider (non-blocking; ignored within 45 s of a decision, then at most once per 90 s). Put it where your plan runs out (e.g. last in a seq or as the final fallback), not where it is reached on every check.
Several conditions in one object mean all of them: {{\"if\": {{\"hunger\": {{\"above\": 60}}, \"has\": {{\"item\": \"food\"}}}}, \"then\": {{\"do\": \"eat\", \"item\": \"food\"}}}}
Conditions C: {{\"hunger\": {{\"above\": 60}}}} {{\"energy\": {{\"below\": 25}}}} {{\"health\": {{\"below\": 40}}}} (0-100) {{\"stamina\": {{\"below\": 30}}}} (breath, 0-100)
  {{\"has\": {{\"item\": \"berries\", \"at_least\": 2}}}} (item \"food\" = any food) {{\"sees\": T}} {{\"near\": {{\"target\": T, \"within\": 3}}}}
  {{\"count\": {{\"of\": \"wolf\" or {{\"kind\": \"person\", \"relation\": \"friend\"}}, \"within\": 8, \"at_least\": 3}}}} (or \"at_most\") how many are in sight; {{\"health_of\": {{\"target\": T, \"below\": 30}}}} how healthy a creature in sight looks (% of full: exact for yourself or one you appraised, else as its wound looks)
  {{\"doing\": {{\"who\": \"person\", \"is\": \"hostile\", \"phase\": \"winding up\", \"at_me\": true, \"within\": 5}}}} someone in sight is visibly doing that now, as a creature's \"visibly\" in your scene shows it (every field optional; who as in count): is = what a creature's \"visibly\".is shows in your scene, or a skill's name, or how it looks (hostile, melee, missile, guard, dash, gesture, work, eat, rest); phase = winding up (all of a windup) | about to release (its second half) | releasing | recovering | holding (a guard held up) | under way (a gesture or work); at_me = aimed at you
  {{\"hurt_within\": 10}} {{\"heard_within\": 20}} {{\"threatened\": true}} {{\"night\": true}} {{\"bedtime\": true}} (your own hours for sleep) {{\"evening\": true}} (your own evening) {{\"work_hours\": true}} (your own working hours) {{\"raining\": true}} {{\"hailed\": 6}} (someone greeted you with a gesture in the last 6 s) {{\"moving\": false}} (you stand still) {{\"believes\": \"judgment_key\"}} or {{\"believes\": {{\"key\": \"k\", \"above\": 0.7}}}}{judged}
  {{\"can\": {{\"do\": \"eat\", \"item\": \"food\"}}}} whether a skill could go ahead now by the world's rules (what it takes is at hand; its target in sight), e.g. {{\"can\": {{\"do\": \"cook\", \"target\": {{\"nearest\": \"campfire\"}}, \"item\": \"fish\"}}}}
  {{\"chance\": 0.2}} {{\"all\": [C, ...]}} {{\"any\": [C, ...]}} {{\"not\": C}}
Targets T: \"self\" \"attacker\" \"speaker\" \"suitor\" (who just offered to start a family with you) \"partner\" (the other parent of your youngest child) \"hailer\" (who just greeted you with a gesture) \"commotion\" (where a fight or a death is, in sight) \"sound\" (toward what you hear and cannot see, when sight depends on facing) \"home\" {{\"nearest\": \"berry_bush\"}} {{\"nearest\": {{\"kind\": \"person\", \"relation\": \"friend\"}}}} (relation: friend|enemy|family, stranger {stranger}, or any label you gave a relationship, e.g. partner)
  {{\"nearest\": {{\"kind\": \"storage\", \"mine\": true}}}} {{\"nearest\": {{\"kind\": \"remains\", \"holds\": \"meat\"}}}} {{\"id\": 6}} {{\"named\": \"Oren\"}} {{\"place\": \"name of a place you remember\"}} {{\"at\": [x, y]}}
  Kinds: berry_bush tree boulder reeds fishing_spot clay_bank | campfire shelter house storage sign gate remains | person deer wolf | grass forest (the nearest tile of that ground in sight).
  People/creature/resource targets resolve only when currently in sight; places and coordinates always resolve. A do-node whose target is missing fails, so \"first\" moves on.
Skills:
{}
- {{\"routine\": \"name\"}} runs one of your routines (named graphs you keep and can rewrite; see below).
- {{\"desires\": [{{\"want\": \"what it is for\", \"weight\": W, \"do\": N}}, ...]}} every check, the strongest desire that can act now wins (a desire whose node fails lets the next one act). \
W = {{\"base\": number, and any of: \"hunger\", \"tired\", \"hurt\", \"night\", \"day\", \"threatened\", \"alone\", \"company\", \"winter\", \"longing\", \"courted\", \"starving\", \"exhausted\", \"rain\", \"hailed\", \"commotion\", \"bedtime\", \"evening\", \"work_hours\": factor, \"believes\": {{\"stance_key\": factor}}}}: \
strength = base + Σ factor × signal, each signal 0..1 (hunger 0 fed..1 starving; tired 0 rested..1 exhausted; hurt; night/day; threatened = an attack or a threat is coming at you; \
alone = no one in sight; company = people in sight; winter; longing = time since this desire last acted, up to an hour; courted = someone in sight just offered to start a family with you; starving = hunger 90+; exhausted = energy 10 or less; rain = it is raining; hailed = someone just greeted you with a gesture; commotion = a fight or a death in sight; bedtime = your own hours for sleep (when you go to bed until you rise); evening = your own evening, the hours before your bedtime; work_hours = your own working hours (with none set, waking hours outside your evening); believes = your stance's value). A desire at or below 0 does not act.
Limits: each graph (your top level, or one routine) at most 64 nodes, depth 10, 12 children per composite. The root restarts whenever it finishes, so a root \"first\" loops forever.
REPERTOIRE: your behavior is a repertoire you build over your life: routines (named graphs) for the things you do, called from a top level, usually desires weighed by what you want. \
Routines are built from skills, and each skill takes something and gives something (see takes/gives above): a routine works only if its earlier steps get what its later steps take, \
e.g. a skill that takes an item from your pack needs a way to get that item when you have none. Waiting gives nothing toward a need. \
Changing a way is itself a skill, rework (an act, see ACTS): you sit still and work out the new version, and you can only rework a way you have lived with \
(each routine shows how it has gone since it last changed: successes, failures and why). Most of the time you live by your ways and only decide your plan; rework one when how it goes shows it is not serving you. \
What you know how to do is what you have built, learned or been taught. \
Make your beliefs act for you: test your judgments and relationships in conditions so you react without having to think again, e.g. {examples}. \
Every branch must lead to action: a guard whose then-branch can only wait blocks everything below it.",
        skills
    );
    if speaks {
        g
    } else {
        g.lines().filter(|l| !l.contains("\"say\"")).collect::<Vec<_>>().join("\n")
    }
}

/// What people are told about deliberate acts (shared by deliberation and conversation).
pub const ACTS: &str = "\
ACTS: deliberate one-off interactions you decide on now. Each is carried out once, in order, right after you decide: \
the body walks to the target, does it by the same rules as anything else (checks, time, effects), and you learn how it went (done, or why not). \
While an act is under way your graph's work waits; only its reflexes (flee, dodge, block, attack, throw, yield) break it off. \
Forms: {\"do\": \"conceive\", \"target\": {\"id\": 6}} (start a family: it happens when you both choose it toward each other within two minutes), \
{\"do\": \"give\", \"target\": {\"id\": 4}, \"item\": \"berries\", \"qty\": 3}, \
{\"do\": \"offer\", \"target\": {\"id\": 4}, \"item\": \"fish\", \"qty\": 2, \"want\": \"wood\", \"want_qty\": 3}, {\"do\": \"accept\", \"target\": {\"id\": 4}, \"offer\": 17} (take what they offered you: \"offer\" names their trade offer, \"record\" their proposed terms, by the id you were shown; without one, their terms come first, then their trade), \
{\"do\": \"decline\", \"target\": {\"id\": 4}, \"offer\": 17} (say no to it: it ends, and they are told), \
{\"do\": \"teach\", \"target\": {\"id\": 6}, \"item\": \"fire\"}, {\"do\": \"tend\", \"target\": {\"id\": 6}}, \
{\"do\": \"host\", \"target\": {\"id\": 6}} (take someone in as your household's guest until morning: a bed in your house, food from its store), \
{\"do\": \"write\", \"item\": \"tablet\"|\"sign\", \"text\": \"your words\", \"topic\": \"a technique you know\"}, {\"do\": \"read\"}, \
{\"do\": \"join\"|\"welcome\", \"target\": {\"id\": 6}}, {\"do\": \"found\", \"text\": \"a name\"}, {\"do\": \"threaten\", \"target\": {\"id\": 6}}, {\"do\": \"seize\", \"target\": {\"id\": 6}, \"item\": \"hide\", \"qty\": 2}, {\"do\": \"yield\", \"target\": {\"id\": 6}}, and any other single piece of work (build, craft, cook, store, take, plant). \
{\"do\": \"rework\", \"item\": \"find food and eat\", \"graph\": {...the whole new version...}} reworks one of your ways (\"retire\": true instead drops it; a new name works out a new way; \
item \"top level\" with a {\"desires\": [...]} graph changes what you weigh and how). \
A single walk ({\"do\": \"goto\", \"target\": T}, with \"run\": true to hurry at the cost of breath) can be a step before an act (e.g. goto a place, then build there); \
following, fleeing, fighting, sleeping and resting are not acts: they are your graph. Words change nothing in the world by themselves: \
if you agree to do something now, do it as an act.";

pub fn identity_system() -> String {
    shared(format!(
            "You create the starting identity of a person in a persistent simulated world. {}\n\n\
The person has lived before this moment: use their background, but give them an individual temperament, private hopes, worries, \
likes and grudges of their own (not a job description; what they did so far is history, not destiny). Write the narrative in the first person, \
2-4 sentences. Relations: how they feel about each person named in the background (trust and affinity -100..100, a label such as \
family, partner, friend, rival, stranger, and a short note in their words). Pastimes: two or three things they enjoy doing for their own sake; calling: the work they love, \
or the one they long for instead. Reply with ONE JSON object: {{\"narrative\": \"...\", \"values\": [...], \"goals\": [...], \"pastimes\": [...], \"calling\": \"...\", \
\"traits\": {{\"caution\": 0-100, \"sociability\": 0-100, \"empathy\": 0-100, \"curiosity\": 0-100, \"ambition\": 0-100, \"introspection\": 0-100, \"temper\": 0-100, \"nurture\": 0-100}}, \"mood\": \"...\", \
\"relations\": [{{\"id\": person id, \"trust\": 0, \"affinity\": 0, \"label\": \"...\", \"note\": \"...\"}}]}}",
            world_rules()
    ))
}

pub fn birth_identity_system() -> String {
    shared(format!(
            "You create the starting identity of a newborn person in a persistent simulated world. {}\n\nThe child has its own temperament: \
traits are influenced by the parents but varied (never copied), and the child knows almost nothing yet. Write the narrative in the first person, \
simple and short, as a very young child. Reply with ONE JSON object: {{\"narrative\": \"...\", \"values\": [...], \"goals\": [...], \
\"traits\": {{\"caution\": 0-100, \"sociability\": 0-100, \"empathy\": 0-100, \"curiosity\": 0-100, \"ambition\": 0-100, \"introspection\": 0-100, \"temper\": 0-100, \"nurture\": 0-100}}, \"mood\": \"...\"}}",
            world_rules()
    ))
}

pub fn identity_user(name: &str, id: u32, knows: &[String], bg: &serde_json::Value, born: Option<&serde_json::Value>) -> String {
    let mut user = Segments::default();
    user.push(
        Stability::Character,
        format!(
            "Person: {} (#{}). Knows how to: {}.\nBackground: {}{}",
            name,
            id,
            if knows.is_empty() { "nothing special".into() } else { knows.join(", ") },
            bg,
            born.map(|t| format!("\nInborn temperament (0-100, use these traits as given): {t}")).unwrap_or_default()
        ),
    );
    user.render()
}

pub fn birth_identity_user(name: &str, id: u32, parents: [(&str, u32, &str); 2], born: Option<&serde_json::Value>) -> String {
    let [(an, aid, ap), (bn, bid, bp)] = parents;
    let mut user = Segments::default();
    user.push(
        Stability::Character,
        format!(
            "Newborn: {} (#{}).\nParent {} (#{}): {}\nParent {} (#{}): {}{}",
            name,
            id,
            an,
            aid,
            ap,
            bn,
            bid,
            bp,
            born.map(|t| format!("\nThe child's inborn temperament (0-100, use these traits as given): {t}")).unwrap_or_default()
        ),
    );
    user.render()
}

/// Thinking: the decision itself, as the person, without the body's grammar (which crowds out
/// the choices of a life: in replays of real moments, 2 in 12 minds acted on a longing for a
/// child with the grammar in view, 11 in 12 without it).
pub fn think_system() -> String {
    think_system_in(frame(), crate::mind::projects::enabled())
}

/// The think system prompt under a frame, with or without projects (`LIVING_PROJECTS`).
fn think_system_in(frame: Frame, projects: bool) -> String {
    shared(format!(
        "{} Stay in character: your personality, values, relationships and memories are yours, \
and they may change through what you live. Start from why you are thinking now: that is what this moment of thought is about. \
Think about it as that person: what you make of it, and what you mean to do. Your body keeps to its habits on its own (eating, sleeping, keeping warm, \
staying safe, your work) unless you decide otherwise, so decide what this moment calls for, not everything. \
When one of your habits keeps failing you (see how each has gone), you may decide to sit down and rework it. \
Speech is how you share yourself: what you think, feel, remember, hope or suspect, as well as practical matters; you may also stay silent. \
Refer to people by the ids you see. Do not assume facts you have not perceived.\n\n{}\n\n\
Reply with ONE JSON object: {{\"thought\": \"what you make of this moment (1-3 sentences)\", \
\"intend\": [\"each thing you mean to do, in plain words, in order (e.g. ask Borno (#5) to start a family with me; give Galy (#8) 2 berries; \
meet Mira (#3) at the ford at dawn; from now on keep watch at night)\"] (may be empty), \
\"say\": {{\"text\": \"...\", \"to\": id or null{}}} or null, \
\"judgments\": [{{\"key\": \"snake_case\", \"value\": 0.0-1.0, \"why\": \"...\"}}] (optional stances), \
\"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}] (optional places worth remembering){}{}}}",
        opening(frame, THINK_OPENING),
        world_rules(),
        say_way_field(),
        if projects { THINK_PROJECTS } else { "" },
        notice_field()
    ))
}

/// The reply field for attention cues (docs/ATTENTION.md) while the world's `cues_on` law
/// holds; empty otherwise. It says what a cue is and what the world does with one, never what
/// to watch for: its examples are placeholders, with no person, duty or situation in them
/// (`cue_examples_name_no_one`).
fn notice_field() -> String {
    let Some(s) = compiled().filter(|s| s.laws().cues_on) else { return String::new() };
    let l = s.laws();
    notice_field_for(l.cue_cooldown_s, l.cue_gap_s)
}

/// The placeholder examples of the cue field.
const CUE_EXAMPLES: &str = "e.g. {\"for\": \"<stance key>\", \"who\": \"wolf\", \"near_me\": 30, \"why\": \"...\"}, \
{\"for\": \"project:<key>\", \"who\": 12, \"doing\": \"<skill>\", \"why\": \"...\"}, {\"for\": \"goal:<its words>\", \"thing\": \"<kind>\", \"at\": \"<one of your places>\", \"why\": \"...\"}";

fn notice_field_for(cooldown_s: f32, gap_s: f32) -> String {
    let span = |s: f32| if s >= 120.0 { format!("{:.0} minutes", s / 60.0) } else { format!("{s:.0} seconds") };
    format!(
        ", \"notice\": [{{\"for\": \"the stance key, project:<key> or goal:<its words> this is about\", \"who\": a person's id, \"unknown\" (anyone whose name you do not know) or a kind of creature, \
\"doing\": \"what they are visibly doing (a skill)\", \"phase\": \"{}\", \"thing\": \"a kind of resource or structure\", \"at\": \"one of your places\", \"within\": metres of it, \"near_me\": metres, \"why\": \"your own words\"}}] \
(optional: what, when you perceive it, should make you think about this again; every field given must hold for the same thing; {CUE_EXAMPLES}. \
You are brought to think by it once per thing per {} and by all of them at most once in {}; you keep at most {}; listing only \"for\" stops watching for it. See # What you watch for)",
        living_rules::doing::Phase::ALL.iter().map(|p| p.word()).collect::<Vec<_>>().join("|"),
        span(cooldown_s),
        span(gap_s),
        crate::memory::CUES
    )
}

/// One line of # What you watch for: what the cue serves and watches for, in the mind's own
/// words, and what came of it (how often it brought the person to think, or why the world does
/// not watch for it). `name` says how the person knows someone by id.
pub fn cue_line(c: &living_bindings::Cue, name: &dyn Fn(u32) -> String, now: u64) -> String {
    let mut what: Vec<String> = Vec::new();
    if c.who_id != 0 {
        what.push(format!("{} (#{})", name(c.who_id), c.who_id));
    } else if c.who == "unknown" {
        what.push("anyone whose name you do not know".into());
    } else if !c.who.is_empty() {
        what.push(format!("a {}", c.who));
    }
    if !c.doing.is_empty() {
        what.push(format!("doing {}", c.doing));
    }
    if !c.phase.is_empty() {
        what.push(c.phase.clone());
    }
    if !c.thing.is_empty() {
        what.push(format!("a {}", c.thing.replace('_', " ")));
    }
    if !c.at.is_empty() {
        what.push(format!("within {:.0} m of {}", c.within, c.at));
    }
    if c.near_me > 0.0 {
        what.push(format!("within {:.0} m of you", c.near_me));
    }
    let why = if c.why.is_empty() { String::new() } else { format!(" (\"{}\")", c.why) };
    let came = if !c.refused.is_empty() {
        format!(": not watched, {}", c.refused)
    } else if c.fires == 0 {
        String::new()
    } else {
        let last = c.fired.iter().map(|f| f.at_ms).max().unwrap_or(0);
        let ago = now.saturating_sub(last) / 60_000;
        format!(": made you think {} time{}, last {}", c.fires, if c.fires == 1 { "" } else { "s" }, if ago == 0 { "just now".to_string() } else { format!("{ago} min ago") })
    };
    format!("for {}: {}{why}{came}", c.for_key, what.join(", "))
}

/// What a deliberation is told of projects (`LIVING_PROJECTS=1`), and the reply field naming
/// the one a decision serves. Says what a project is, never what to want.
const THINK_PROJECTS: &str = ", \"serves\": \"the key of the project under # Your projects that this decision works toward, or null\"";

/// What consolidation is told of projects (`LIVING_PROJECTS=1`). Says what a project is and how
/// to keep it, never what to want.
const CONSOLIDATE_PROJECTS: &str = "\n\nPROJECTS (# Your projects): what the person has set out to achieve over days, in their own words. \
They are the person's own, from who they are and what they have lived; nobody gives them one. When the person sets out on something, \
take it up; as it moves, revise its progress and next step; when it is achieved or given up, end it. A person pursues a few at a time \
(at most 3); one never taken up again fades. Optional reply field: \"projects\": [{\"key\": \"project:<slug>\", \"aim\": \"...\", \
\"progress\": \"...\", \"next_step\": \"...\", \"because\": [experience ids]}, {\"key\": ..., \"ended\": \"done|dropped\", \"why\": \"...\"}].";

/// The projects section of a prompt (empty with the switch off).
fn projects_section(out: &mut Segments, projects: &str) {
    if !projects.is_empty() {
        out.push(Stability::Character, format!("\n# Your projects (what you have set out to achieve; key: aim)\n{projects}"));
    }
}

pub fn think_user(c: &Ctx, scene: &str, plan: &str, reason: &str, habits: &str, projects: &str) -> String {
    let mut out = Segments::default();
    common(c, &mut out);
    out.push(Stability::Character, format!("\n# Your habits (your body keeps to them)\n{habits}\n"));
    projects_section(&mut out, projects);
    out.push(Stability::Dynamic, format!("\n# Why you are thinking now\n{reason}\n\n"));
    out.push(Stability::Dynamic, "\n# Recent experiences (oldest first)\n");
    for e in &c.experiences {
        out.push(Stability::Dynamic, format!("- {e}\n"));
    }
    out.push(Stability::Dynamic, format!("\n# What you perceive right now\n{scene}\n"));
    out.push(Stability::Dynamic, format!("\n# What you were doing\n{plan}\n"));
    out.render()
}

/// Compiling: the body's expression of a decision already made (acts now, an intent over time).
pub fn compile_user(decision: &str, mut deliberate: Segments) -> String {
    deliberate.push(Stability::Dynamic, format!("\n# What you decided (express exactly this: add nothing, drop nothing)\n{decision}\n\n"));
    deliberate.render()
}

pub fn deliberate_system() -> String {
    deliberate_system_in(frame())
}

fn deliberate_system_in(frame: Frame) -> String {
    shared(format!(
        "{} Stay in character: your personality, values, relationships and memories are yours, \
and they may change through what you live. That person has already decided what to do (see What you decided): express that decision as deliberate acts to carry out now (in order) and, for what goes on over time, an intent weighed among your desires, or routine changes. Don't add intentions of your own or drop any; leave speech to the decision (speaking is not an act).\n\n{}\n\n{}\n\n{}\n\n\
A graph can span a whole day: hour conditions ({{\"hour\": {{\"above\": 6, \"below\": 12}}}}) let you do different things at different times. \
Your top level and your routines are all your body does: they began as your habits and they are yours; nothing eats, sleeps or keeps you warm unless they do. \
To change one, rework it as an act, when what you decided says so. \
Refer to people by the ids you see. Do not assume facts you have not perceived. Reply with ONE JSON object:\n\
{{\"acts\": [ACTS to carry out now, in order] (optional), \
\"plan\": \"one-line intention\", \"intent\": {{\"weight\": 0.1-1.5, \"graph\": {{...what you mean to do...}}}} (becomes your routine \"current plan\", \
weighed among your desires as \"the plan\": your top level shows each desire's weight; a plan weighed above your safety desire outweighs staying safe while it lasts, and needs keep their own pull, e.g. strong hunger ≈ 1.0, so a plan of 0.6 yields to it and resumes after), \
\"graph\": \"keep\" (a graph here counts as your intent), \
or instead of graph \"patch\": {{\"label\": \"combat\", \"graph\": {{...}}}} to replace only that labeled branch (e.g. adapt how you fight mid-fight) and keep the rest}}",
        opening(frame, THINK_OPENING),
        world_rules(),
        grammar(),
        ACTS
    ))
}

pub fn consolidate_system() -> String {
    consolidate_system_in(frame(), crate::mind::projects::enabled())
}

/// The consolidation system prompt under a frame, with or without projects (`LIVING_PROJECTS`).
fn consolidate_system_in(frame: Frame, projects: bool) -> String {
    shared(format!(
        "{} \
You keep the person's mind as a graph that you shape freely: concepts (people, places, things, ideas, plans, fears, customs, promises...) \
and relationships between them, named in your own words (any labels, any relationship names, any properties). \
Integrate the new experiences: record what the person now takes to be true, feels, intends or suspects. It may be wrong; \
hearsay stays hearsay (e.g. person:4 -CLAIMED-> idea:wolves_at_ford). Don't transcribe routine: capture meaning, patterns and \
changes. Above all, REVISE: check the existing mind for anything these experiences contradict, weaken, strengthen or make \
outdated, and change it — re-assert an edge with a new confidence, retract what is no longer held, give a concept the labels \
that fit it now (labels you give REPLACE its old ones, e.g. a Stranger who became a Friend), clear a property with null, and \
merge concepts that turn out to be the same thing. Prefer connecting to existing concepts over inventing new ones. \
History is kept automatically. Keep as memories only the \
few experiences the person would still remember tomorrow (at most 3, often none), each with a gist in the person's own words{}. Identity (narrative, values, goals, traits 0-100, \
mood) changes only when experiences genuinely warrant it; otherwise identity is null. When it changes, it follows the life the person has lived: goals and values \
grow out of what they did, tried, met and went through, and name the people, places and things in that life they are about; a feeling that comes and goes \
(restlessness, loneliness, a longing) is felt, and belongs to mood and memory until the person's life gives it someone or something to turn to.{}\n\n{}\n\n\
KEYS: anchors connect your mind to the world: \"self\", \"person:<numeric id>\" (e.g. \"person:7\", never a name), \"place:<name>\", \"kind:<wolf|deer|berry_bush|campfire|...>\", \
\"know:<technique>\" (the technique itself, e.g. \"know:cooking\"). \
Any other key is yours to invent (\"idea:shared_storage\", \"plan:river_camp\"). Reuse existing keys shown in your mind.\n\
The body acts on three parts of the mind without thinking: how the person feels about people (self -FEELS {{trust, affinity -100..100, label, note}}-> person:<id>), \
stances the behavior graph can test (self -JUDGES {{value 0..1, why}}-> stance:<key>, e.g. stance:wolves_hunt_near_camp; stances relax toward 0.5 unless reinforced) \
and places with coordinates (place:<name> with props x, y). You can write those edges directly, or use the shorthand arrays below \
(relations, judgments, places), which become exactly those edges. Keep stance keys stable.\n\n\
Reply with ONE JSON object:\n\
Keep the reply compact: at most 12 nodes and 20 edges (meaning and change, not every event).\n\
{{\"summary\": \"what this meant to the person (1-2 sentences)\",\n\
 \"remember\": [{{\"exp\": experience id, \"gist\": \"...\"}}],\n\
 \"nodes\": [{{\"key\": \"person:4\", \"labels\": [\"Person\", \"Rival\"], \"name\": \"Bram\", \"props\": {{...}}}}],\n\
 \"edges\": [{{\"from\": \"person:4\", \"rel\": \"TOOK_FOOD_FROM\", \"to\": \"place:our_storage\", \"confidence\": 0.0-1.0, \"because\": [experience ids], \"props\": {{...}}}}],\n\
 \"retract\": [{{\"from\": \"self\", \"rel\": \"TRUSTS\", \"to\": \"person:4\"}}],\n\
 \"merge\": [{{\"from\": \"idea:kael_seems_kind\", \"into\": \"idea:kael_is_friendly\"}}],\n\
 \"relations\": [{{\"id\": person id, \"trust\": 0, \"affinity\": 0, \"label\": \"friend|family|partner|ally|rival|enemy|stranger|...\", \"note\": \"short\", \"because\": [experience ids]}}],\n\
 \"judgments\": [{{\"key\": \"...\", \"value\": 0.0-1.0, \"why\": \"...\", \"because\": [experience ids]}}],\n\
 \"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}],\n\
 \"identity\": null or {{\"narrative\": \"first person, 2-4 sentences\", \"values\": [...], \"goals\": [...], \"pastimes\": [...], \"calling\": \"...\", \"traits\": {{...}}, \"mood\": \"...\", \"why\": \"what changed\"}}{}}}",
        opening(frame, CONSOLIDATE_OPENING),
        if lessons() { LESSON } else { "" },
        if projects { CONSOLIDATE_PROJECTS } else { "" },
        world_rules(),
        notice_field()
    ))
}

/// Memory for a character a human plays (docs/PLAYER_MEMORY.md). Nothing in it is about one
/// character, so every player's request shares this prefix (provider-side prompt caching).
/// The person's choices are the player's: their acts and words are recorded as acts and
/// words, never with reasons nobody perceived. The identity (narrative, values, traits, mood)
/// is inferred from that conduct (decided 2026-11-09), and only when it says something new.
pub fn internalize_system() -> String {
    shared(format!(
        "You are the memory of the person described under # Who you are, in a persistent simulated world. \
The person's choices are made by someone you cannot see: you know only what the person perceived and did (what they did, said and \
heard, what happened to them and where), never why. Record what they did and said as acts and words (self -SAID_TO-> person:7, \
self -FOUGHT-> kind:wolf), and what they now know or can expect from what they perceived (who is friendly, what is dangerous, where \
things are). Never invent motives, feelings, plans or thoughts they did not express. What others told them stays what others claimed \
(person:4 -CLAIMED-> idea:wolves_at_ford). Keep the mind as a graph you shape freely: concepts (people, places, things, ideas, \
promises...) and relationships named in your own words. REVISE: check the existing mind for anything these experiences contradict, \
strengthen or make outdated, and change it (re-assert an edge with a new confidence, retract, relabel, merge). Prefer connecting to \
existing concepts. Don't transcribe routine: keep meaning and change. Keep as memories only the few experiences the person would \
still remember tomorrow (at most 4, often fewer), each with a gist in the person's own words that says what happened, not why. \
IDENTITY is the one place where you read character from conduct: who the person shows themselves to be through what they did and said \
(a first-person narrative of their life so far, values their acts keep to, traits 0-100 such as caution, warmth or boldness, and their \
mood as their words and acts showed it). Infer it only from what these experiences and the mind show, revise the identity under \
# Who you are rather than replace it, and give null when nothing new shows.\n\n{}\n\n\
KEYS: anchors connect the mind to the world: \"self\", \"person:<numeric id>\" (e.g. \"person:7\", never a name), \"place:<name>\", \
\"kind:<wolf|deer|berry_bush|tree|...>\", \"know:<technique>\". Any other key is yours to invent. Reuse existing keys shown in the mind.\n\
How the person stands with people they met, from what passed between them (self -FEELS {{trust, affinity -100..100, label, note}}-> person:<id>), \
stances their experience supports (self -JUDGES {{value 0..1, why}}-> stance:<key>, e.g. stance:wolves_attack_newcomers) and places with \
coordinates (place:<name> with props x, y; experience lines give where they happened) can be written as edges or with the shorthand arrays.\n\n\
Reply with ONE JSON object, compact (at most 12 nodes and 20 edges):\n\
{{\"summary\": \"what happened to the person (1-2 sentences, no motives)\",\n\
 \"remember\": [{{\"exp\": experience id, \"gist\": \"...\"}}],\n\
 \"nodes\": [{{\"key\": \"person:4\", \"labels\": [\"Person\"], \"name\": \"Bram\", \"props\": {{...}}}}],\n\
 \"edges\": [{{\"from\": \"self\", \"rel\": \"ASKED_ABOUT_FOOD\", \"to\": \"person:4\", \"confidence\": 0.0-1.0, \"because\": [experience ids], \"props\": {{...}}}}],\n\
 \"retract\": [{{\"from\": \"self\", \"rel\": \"...\", \"to\": \"...\"}}],\n\
 \"merge\": [{{\"from\": \"key\", \"into\": \"key\"}}],\n\
 \"relations\": [{{\"id\": person id, \"trust\": 0, \"affinity\": 0, \"label\": \"stranger|acquaintance|friend|rival|enemy|...\", \"note\": \"short\", \"because\": [experience ids]}}],\n\
 \"judgments\": [{{\"key\": \"...\", \"value\": 0.0-1.0, \"why\": \"...\", \"because\": [experience ids]}}],\n\
 \"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}],\n\
 \"identity\": null or {{\"narrative\": \"first person, 2-4 sentences\", \"values\": [...], \"traits\": {{...}}, \"mood\": \"...\", \"why\": \"what their conduct showed\"}}}}",
        world_rules()
    ))
}

/// Kept memories carry what they taught (opt-in experiment: `LIVING_LESSONS=1`; off by
/// default). A lesson told with its story may carry to new situations better than a rule;
/// whether it does, and what it costs in tokens, is for an A/B lab to show.
fn lessons() -> bool {
    matches!(std::env::var("LIVING_LESSONS").as_deref(), Ok("1") | Ok("on") | Ok("true"))
}

const LESSON: &str = ": what happened and, when it taught the person something, what it taught, as they would tell it \
(e.g. \"The night the wolves came to the ford, Bram's goats were gone by dawn: wolves follow the water in winter\")";

pub fn reorganize_system() -> String {
    shared(format!(
        "You are the mind of the person described under # Who you are, resting. Tidy the person's mind the way sleep does, without inventing anything new that happened: \
merge concepts that are really the same thing (keep the clearer key), generalize repeated specifics into lasting patterns and then retract \
the specifics (e.g. many SAW edges to kind:wolf → one pattern such as kind:wolf -HUNTS_NEAR-> place:ford), relabel concepts whose role \
changed, retract what the person no longer holds or that no longer matters, and strengthen what keeps proving true. Aim for a smaller, \
better connected mind that still contains everything the person cares about. Anchor keys (self, person:<id>) cannot be merged away.\n\n\
Reply with ONE JSON object: {{\"summary\": \"how the person's understanding settled (1-2 sentences)\", \
\"merge\": [{{\"from\": key, \"into\": key}}], \"nodes\": [{{\"key\": ..., \"labels\": [...], \"name\": ..., \"props\": {{...}}}}], \
\"edges\": [{{\"from\": key, \"rel\": \"...\", \"to\": key, \"confidence\": 0.0-1.0, \"because\": [experience ids from the edges you generalize]}}], \
\"retract\": [{{\"from\": key, \"rel\": \"...\", \"to\": key}}], \"judgments\": [{{\"key\": ..., \"value\": 0.0-1.0, \"why\": ...}}]{}}}",
        if crate::mind::projects::enabled() { REORGANIZE_PROJECTS } else { "" }
    ))
}

/// The reorganization may revise, merge or end projects too (`LIVING_PROJECTS=1`).
const REORGANIZE_PROJECTS: &str = ", \"projects\": [as # Your projects shows them, revised: {\"key\", \"aim\", \"progress\", \"next_step\"}, or ended: {\"key\", \"ended\": \"done|dropped\", \"why\"}] (optional; the person's own aims, kept, merged or ended as their life shows)";

pub fn reorganize_user(name: &str, persona: &str, concepts: &[String], edges: &[String], projects: &str) -> String {
    let mut out = Segments::default();
    out.push(Stability::Shared, "Respond with the JSON object.\n\n");
    out.push(Stability::Character, format!("# Who you are\n{name}\n{persona}\n"));
    projects_section(&mut out, projects);
    out.push(Stability::Dynamic, "\n# Your concepts (key \"name\" [labels] {properties} — links)\n");
    for c in concepts {
        out.push(Stability::Dynamic, format!("- {c}\n"));
    }
    out.push(Stability::Dynamic, "\n# Your current beliefs and links (strength after fading, when last reinforced)\n");
    for e in edges {
        out.push(Stability::Dynamic, format!("- {e}\n"));
    }
    out.render()
}

pub struct Ctx<'a> {
    pub name: &'a str,
    pub clock: String,
    /// How the character's body feels now, in words (`felt_body`); empty where not shown.
    pub body: String,
    pub persona: String,
    pub relations: Vec<String>,
    pub mind: Vec<String>,
    pub memories: Vec<String>,
    pub judgments: Vec<String>,
    pub places: Vec<String>,
    pub experiences: Vec<String>,
    /// Agreements, demands and one's people's standing, as the world keeps them (its records).
    pub dealings: Vec<String>,
    /// Attention cues as the world keeps them (`None`: the `cues_on` law is off and the
    /// section is left out).
    pub cues: Option<Vec<String>>,
}

fn common(c: &Ctx, out: &mut Segments) {
    out.push(Stability::Shared, "Respond with the JSON object.\n\n");
    out.push(Stability::Character, format!("# Who you are ({})\n{}\n", c.name, c.persona));
    out.push(Stability::Dynamic, format!("\nNow {}\n", c.clock));
    if !c.body.is_empty() {
        out.push(Stability::Dynamic, format!("How your body feels: {}\n", c.body));
    }
    if !c.dealings.is_empty() {
        out.push(Stability::Dynamic, "\n# Your dealings and your people's standing (as the world keeps them)\n");
        for d in &c.dealings {
            out.push(Stability::Dynamic, format!("- {d}\n"));
        }
    }
    out.push(Stability::Character, "\n# People you know\n");
    if c.relations.is_empty() {
        out.push(Stability::Character, "(nobody yet)\n");
    }
    for r in &c.relations {
        out.push(Stability::Character, format!("- {r}\n"));
    }
    out.push(Stability::Dynamic, "\n# What comes to mind (recalled by what you perceive, what is happening and why; what you hold true, feel and intend; keys in parentheses)\n");
    if c.mind.is_empty() {
        out.push(Stability::Dynamic, "(nothing yet)\n");
    }
    for f in &c.mind {
        out.push(Stability::Dynamic, format!("- {f}\n"));
    }
    if !c.memories.is_empty() {
        out.push(Stability::Dynamic, "\n# Memories this brings back\n");
        for m in &c.memories {
            out.push(Stability::Dynamic, format!("- {m}\n"));
        }
    }
    out.push(Stability::Dynamic, "\n# Your stances on your mind now (usable as {\"believes\": key})\n");
    if c.judgments.is_empty() {
        out.push(Stability::Dynamic, "(none)\n");
    }
    for j in &c.judgments {
        out.push(Stability::Dynamic, format!("- {j}\n"));
    }
    if let Some(cues) = &c.cues {
        out.push(Stability::Dynamic, "\n# What you watch for (each makes you think when you perceive it)\n");
        if cues.is_empty() {
            out.push(Stability::Dynamic, "(nothing)\n");
        }
        for q in cues {
            out.push(Stability::Dynamic, format!("- {q}\n"));
        }
    }
    out.push(Stability::Character, "\n# Places you remember\n");
    if c.places.is_empty() {
        out.push(Stability::Character, "(none)\n");
    }
    for p in &c.places {
        out.push(Stability::Character, format!("- {p}\n"));
    }
}

/// A body's needs and health at one moment, with how they are changing (per minute).
#[derive(Clone, Debug, Default)]
pub struct Body {
    pub hp: f32,
    pub max_hp: f32,
    pub hunger: f32,
    pub energy: f32,
    pub hp_rate: f32,
    /// The vitals row's numeric fields by name as read (`vitals`: every column, so a vital a
    /// world adds reaches the `status_of` law), and when; empty: the five numbers above, now.
    pub row: Vec<(String, f64)>,
    pub now_ms: u64,
    pub kind: String,
    pub stage: String,
    pub night: bool,
}

impl Body {
    /// The body as the `status_of` law reads it.
    pub fn facts(&self, sc: &living_rules::script::Scripts) -> living_rules::script::BodyFacts {
        let row = if self.row.is_empty() {
            vec![("hp".into(), self.hp as f64), ("max_hp".into(), self.max_hp as f64), ("hunger".into(), self.hunger as f64), ("energy".into(), self.energy as f64), ("hp_rate".into(), self.hp_rate as f64)]
        } else {
            self.row.clone()
        };
        let kind = if self.kind.is_empty() { "person" } else { &self.kind };
        let stage = if self.stage.is_empty() { "adult" } else { &self.stage };
        living_rules::script::BodyFacts::of(kind, stage, self.night, &row, sc.meters(), self.now_ms)
    }
}

/// The body as its owner feels it, in plain words and no numbers: the `felt` words of the
/// world's `status_of` law, the thresholds the authority's bodily alarms and the players'
/// screens use. Empty when the law gives none.
pub fn felt_body(b: &Body) -> String {
    let Some(sc) = compiled() else { return String::new() };
    sc.felt(&b.facts(&sc)).unwrap_or_else(|e| {
        log::warn!("felt_body: {e}");
        String::new()
    })
}

/// Each meter's felt word (`{"health": "unhurt", "hunger": "very hungry", …}`), from the same law.
pub fn felt_by_meter(b: &Body) -> Vec<(String, String)> {
    let Some(sc) = compiled() else { return Vec::new() };
    sc.felt_by_meter(&b.facts(&sc)).unwrap_or_default()
}

/// Whether it is night at `hour` by the world's `daylight` law.
pub fn is_night(hour: f32) -> bool {
    compiled().is_some_and(|sc| sc.is_night(hour))
}

/// The fast lane's system prompt (docs/FAST_LANE.md): the person, the world's rules (physics) and
/// the graph grammar, and the four answers it may give. No acts, no dealings, no tactics: what to
/// do is the character's own.
pub fn fast_system() -> String {
    fast_system_in(frame())
}

fn fast_system_in(frame: Frame) -> String {
    shared(format!(
        "{} Stay in character: your personality, values, relationships and memories are yours. \
Something has just happened to you (see Why now). Your body goes on doing what your top level and your routines say while you think; \
what you answer changes them from the next moment on, not the moment that is passing. \
You may rewrite your `combat` branch, rewrite one of the routines listed under Your routines, switch your `combat` branch to one of them, or keep everything as it is. \
Use only what you have perceived and what you know how to do. Refer to people by the ids you see. Reply with ONE JSON object, one of:\n\
{{\"patch\": {{\"label\": \"combat\", \"graph\": {{...}}}}, \"thought\": \"one sentence, in your words\"}}\n\
{{\"routine\": {{\"name\": \"one of your routines\", \"graph\": {{...}}}}, \"thought\": \"...\"}}\n\
{{\"switch\": \"one of your routines\", \"thought\": \"...\"}}\n\
{{\"keep\": true, \"thought\": \"...\"}}",
        opening(frame, THINK_OPENING),
    )) + "\n\n" + &*world_rules() + "\n\n" + grammar().as_str()
}

/// The fast lane's user prompt: who the character is (with its own moves' timings), its top
/// level and its routines, then why now (the event as perceived) and what has just happened.
/// Ordered from the most to the least stable between one character's fast calls, so a
/// provider's prefix cache can reuse the person, the plan and the routines across the calls of
/// one fight (docs/FAST_LANE.md); the content is the same in any order.
pub fn fast_user(reason: &str, persona: &str, experiences: &[String], plan: &str, outline: &str, repertoire: &str) -> String {
    let mut out = format!("# Who you are\n{persona}\n\n# Your top level (plan: {plan})\n{outline}\n");
    if !repertoire.is_empty() {
        out.push_str(&format!("\n# Your routines\n{repertoire}\n"));
    }
    out.push_str(&format!("\n# Why now\n{reason}\n\n# What has just happened (oldest first)\n"));
    for e in experiences {
        out.push_str(&format!("- {e}\n"));
    }
    out
}

pub fn deliberate_user(c: &Ctx, scene: &str, graph_outline: &str, plan: &str, reason: &str, repertoire: &str) -> Segments {
    let mut out = Segments::default();
    out.push(Stability::Dynamic, format!("\n# Why you are thinking now\n{reason}\n\n"));
    common(c, &mut out);
    out.push(Stability::Dynamic, "\n# Recent experiences (oldest first)\n");
    for e in &c.experiences {
        out.push(Stability::Dynamic, format!("- {e}\n"));
    }
    out.push(Stability::Dynamic, format!("\n# What you perceive right now\n{scene}\n"));
    out.push(Stability::Dynamic, format!("\n# Your top level (plan: {plan})\n{graph_outline}\n"));
    if !repertoire.is_empty() {
        out.push(Stability::Character, format!("\n# Your routines\n{repertoire}\n"));
    }
    out
}

pub fn consolidate_user(c: &Ctx, projects: &str) -> String {
    let mut out = Segments::default();
    common(c, &mut out);
    projects_section(&mut out, projects);
    out.push(Stability::Dynamic, "\n# New experiences to integrate (oldest first; [experience id] time text)\n");
    for e in &c.experiences {
        out.push(Stability::Dynamic, format!("- {e}\n"));
    }
    out.render()
}

// ---- animal minds ----------------------------------------------------------------------

pub fn animal_think_system(kind: &str, nature: &str) -> String {
    shared(format!(
        "You are the mind of the {kind} described under # Who you are. {nature}\n\
Feel the moment as the animal does. Answer with ONE JSON object of two short strings, in plain simple words: \
{{\"feeling\": \"what you sense and feel right now\", \"impulse\": \"what you want to do now, and what you avoid\"}}"
    ))
}

pub fn animal_think_user(name: &str, kind: &str, temperament: &str, mind: &[String], experiences: &[String], scene: &str, reason: &str) -> String {
    let (scene, smells) = split_smells(scene);
    let mut out = Segments::default();
    out.push(Stability::Character, format!("# Who you are\n{name}, a {kind}.\nYour temperament: {temperament}.\n"));
    out.push(Stability::Dynamic, "# What you associate\n");
    if mind.is_empty() {
        out.push(Stability::Dynamic, "(nothing yet)\n");
    }
    for m in mind {
        out.push(Stability::Dynamic, format!("- {m}\n"));
    }
    out.push(Stability::Dynamic, "\n# What just happened\n");
    for e in experiences {
        out.push(Stability::Dynamic, format!("- {e}\n"));
    }
    out.push(Stability::Dynamic, format!("\n# Around you now\n{scene}\n"));
    if !smells.is_empty() {
        out.push(Stability::Dynamic, "\n# What you smell, out of sight\n");
        for s in &smells {
            out.push(Stability::Dynamic, format!("- {s}\n"));
        }
    }
    out.push(Stability::Dynamic, format!("\n# Why you stir\n{reason}\n"));
    out.render()
}

/// An animal choosing among a few things it can do (`LIVING_ANIMAL_MINDS=choose`): one call in
/// place of an impulse and a compiled graph.
pub fn animal_choose_system(kind: &str, nature: &str) -> String {
    shared(format!(
        "You are the mind of the {kind} described under # Who you are. {nature}\n\
Feel the moment as the animal does, then pick one of the numbered options under # What you can do now, and how strongly you mean it \
(\"low\", \"mid\" or \"high\"). Your instincts keep working underneath whatever you pick. \
Answer with ONE JSON object: {{\"feeling\": \"what you sense and feel, in plain simple words\", \"pick\": the option's number, \"strength\": \"low|mid|high\"}}"
    ))
}

/// What an animal choosing is told: what it would be told to feel an impulse, and the
/// options. It decides for itself alone (docs/PACK_MIND.md: the `pack` switch is retired).
pub fn animal_choose_user(think_user: String, options: &[String]) -> String {
    let mut out = think_user;
    out.push_str("\n# What you can do now\n");
    for (i, o) in options.iter().enumerate() {
        out.push_str(&format!("{i}. {o}\n"));
    }
    out
}

/// A scene without its smelled creatures, and those as the animal senses them
/// ("You smell a deer to the northeast, far, about 40 tiles.").
fn split_smells(scene: &str) -> (String, Vec<String>) {
    let Ok(mut v) = serde_json::from_str::<serde_json::Value>(scene) else { return (scene.to_string(), Vec::new()) };
    let Some(list) = v.as_object_mut().and_then(|o| o.remove(living_rules::species::SMELLED)) else { return (scene.to_string(), Vec::new()) };
    let lines = list
        .as_array()
        .into_iter()
        .flatten()
        .map(|c| format!("You smell a {} to the {}, {}.", c["kind"].as_str().unwrap_or("creature"), c["dir"].as_str().unwrap_or("distance"), c["dist"].as_str().unwrap_or("far")))
        .collect();
    (v.to_string(), lines)
}

/// What an animal's graph compiler is told about its body's smell.
pub fn scent_help(sp: &living_rules::species::Species) -> String {
    let Some(s) = sp.scent.as_ref().filter(|s| !s.kinds.is_empty()) else { return String::new() };
    let example = &s.kinds[0];
    format!(
        "SMELL: it smells {} within about {:.0} tiles, beyond sight; the scene lists them under \"{}\" (kind, rough direction and distance, id). \
A skill's creature target ({{\"nearest\": \"{example}\"}} or {{\"id\": n}}) is the nearest one seen or, when none is seen, the nearest one smelled: \
{{\"do\": \"goto\", \"target\": {{\"nearest\": \"{example}\"}}}} follows the scent and flee moves away from it (attacking still needs reach). \
\"sees\", \"near\", \"count\" and \"health_of\" are sight only; {{\"smells\": T}} holds while T is within smell, e.g. {{\"if\": {{\"smells\": {{\"nearest\": \"{example}\"}}}}, \"then\": N}}.",
        s.kinds.join(", "),
        s.radius,
        living_rules::species::SMELLED
    )
}

pub fn animal_compile_system(kind: &str, skills: &str, signals: &str, scent: &str, max_nodes: usize) -> String {
    shared(format!(
        "You turn the current impulse of a {kind} into what it does now. Its instincts (routines for staying safe, feeding, \
resting, mating, keeping with its kind and roaming, weighed by a top level of desires) are inherited: they change over \
generations, not by one animal's impulse, and they keep working underneath. The impulse is one more pull among them, \
lasting about a minute. Do not add plans, knowledge or wisdom the animal does not have, and keep the graph short \
(at most {max_nodes} nodes). The {kind} cannot speak; it communicates only with its signals: {signals} \
(as {{\"do\": \"signal\", \"item\": name}}).\n\n{}\n{scent}\n\n\
Reply with ONE JSON object: {{\"intent\": {{\"weight\": 0.1-1.5, \"graph\": {{...what the impulse makes it do...}}}} \
(weighed among its desires, whose weights its top level shows: an intent weighed above its safety desire outweighs fleeing danger while it lasts), \
or {{\"graph\": \"keep\"}} when the impulse needs nothing its instincts don't already do}}",
        grammar_with(skills, false)
    ))
}

pub fn animal_compile_user(name: &str, kind: &str, impulse: &str, feeling: &str, scene: &str, top: &str, routines: &str) -> String {
    let mut out = Segments::default();
    out.push(Stability::Character, format!("{name} the {kind}\n"));
    out.push(Stability::Character, format!("\n\nIts routines (how each has gone):\n{routines}"));
    out.push(Stability::Dynamic, format!("\nImpulse: {impulse}\nFeeling: {feeling}\n\nAround it now:\n{scene}\n\nIts top level (what it weighs):\n{top}"));
    out.render()
}

pub fn animal_consolidate_system(kind: &str, nature: &str) -> String {
    shared(format!(
        "You are the memory of the {kind} described under # Who you are. {nature}\n\
Animals remember through blunt associations: where food or danger was, which creatures hurt or fed you, who belongs to your \
herd or pack, smells and sounds and what followed them. Record only a few such associations as graph edits. There is no life \
story: identity is only temperament and mood, which shift a little after strong experiences (more fearful after being hurt, \
bolder after success). Keys: \"self\", \"person:<id>\", \"kind:<wolf|deer|person|...>\", \"place:<name>\"; the ids of your own kind are in the text.\n\
Reply with ONE JSON object: {{\"summary\": \"...\", \"nodes\": [...], \"edges\": [{{\"from\", \"rel\", \"to\", \"confidence\", \"because\": [ids]}}], \
\"retract\": [...], \"relations\": [{{\"id\": creature id, \"trust\", \"affinity\", \"label\": \"pack|herd|mate|threat|prey|...\", \"because\": [experience ids]}}], \
\"judgments\": [{{\"key\": \"ford_smells_of_wolves\", \"value\": 0.0-1.0, \"why\": \"...\", \"because\": [experience ids]}}], \"places\": [{{\"name\", \"x\", \"y\"}}], \
\"identity\": null or {{\"traits\": {{...}}, \"mood\": \"...\", \"why\": \"...\"}}}}"
    ))
}

/// A conversation turn: no world rules or graph grammar, just the person, the other and the talk.
pub fn talk_system() -> String {
    talk_system_in(frame())
}

fn talk_system_in(frame: Frame) -> String {
    shared(format!(
        "{} \
This is your turn in a conversation. Talk as yourself, in your own voice, usually a sentence or two: answer what was just said, \
or say what you actually want to say — what you think or feel, something you remember, a question, a proposal, a refusal, a joke. \
Real conversations are short and have a point. As soon as something is settled between you (you agreed on something, \
one of you declined, someone will think it over, or there is simply nothing more to say), say so in \"settled\": that line closes \
the conversation for now; don't restate what was already agreed or keep saying goodbye. You don't have to answer everything: \
silence (say null) is fine. Reply with ONE JSON object: {{\"thought\": \"what you privately make of this (one sentence)\", \
\"say\": \"your words\" or null, \"to\": id of who you speak to, {}\
\"acts\": [] or deliberate acts you carry out now, e.g. {{\"do\": \"conceive\", \"target\": {{\"id\": id of who you speak to}}}} once you both want a child together, \
{{\"do\": \"accept\", \"target\": {{\"id\": id of who you speak to}}, \"offer\": id of their offer}} to take a trade they offered (\"record\": id of their proposal, for terms), \
{{\"do\": \"decline\", \"target\": {{\"id\": id of who you speak to}}, \"offer\": id of their offer}} to say no to it, {{\"do\": \"give\", \"target\": {{\"id\": id of who you speak to}}, \"item\": \"berries\", \"qty\": 2}}, \
{{\"do\": \"offer\", \"target\": {{\"id\": id of who you speak to}}, \"item\": \"fish\", \"qty\": 2, \"want\": \"wood\", \"want_qty\": 3}}, {{\"do\": \"teach\", \"target\": {{\"id\": id of who you speak to}}, \"item\": \"fire\"}}, \
{{\"do\": \"host\", \"target\": {{\"id\": id of who you speak to}}}} to take them in as your household's guest until morning \
(words change nothing in the world by themselves: what you agree to do now, do here; you will learn how it went), \
\"settled\": null while the matter is still open, or what is now settled, in a few words (e.g. \"meet at the ford at dawn\", \"she will think about it\", \"I refused\", \"nothing more to say\"), \
\"until\": null or when to take it up again (\"dawn\", \"morning\", \"noon\", \"evening\", \"night\", \"tomorrow\" or an hour 0-23), \
\"end\": true if this is your last word for now}}{}",
        opening(frame, TALK_OPENING),
        ways_text(),
        match talk_acts() {
            a if a.is_empty() => String::new(),
            a => format!("\nOther acts you may carry the same way (\"target\": {{\"id\": id of who you speak to}}), as the world's rules describe them:\n{a}"),
        }
    ))
}

/// What a conversation turn is told.
pub struct TalkUser<'a> {
    pub name: &'a str,
    pub identity: &'a str,
    pub pacing: &'a str,
    pub other: &'a str,
    pub other_id: u32,
    pub feeling: &'a str,
    pub mind: &'a [String],
    pub memories: &'a [String],
    pub lately: &'a [String],
    pub earlier: Option<&'a str>,
    pub scene: &'a str,
    /// How one's body feels (`felt_body`); empty when unknown.
    pub body: &'a str,
    pub conversation: &'a [String],
    pub heard: &'a str,
    /// How it was said, when that matters for the answer (a whisper, a call from afar).
    pub how: &'a str,
    /// Standing proposals between the two, what one carries and knows (for acts).
    pub between: &'a [String],
}

pub fn talk_user(t: &TalkUser) -> String {
    let (other, other_id) = (t.other, t.other_id);
    let mut out = Segments::default();
    out.push(Stability::Shared, "Your turn. Respond with the JSON object.\n\n");
    out.push(Stability::Character, format!("# Who you are\n{}\n{}\n\n# How you talk\n{}\n\n# You and {other} (#{other_id})\n{}\n", t.name, t.identity, t.pacing, t.feeling));
    if !t.mind.is_empty() || !t.memories.is_empty() {
        out.push(Stability::Dynamic, "\n# What comes to mind\n");
        for b in t.mind {
            out.push(Stability::Dynamic, format!("- {b}\n"));
        }
        for m in t.memories {
            out.push(Stability::Dynamic, format!("- you remember: {m}\n"));
        }
    }
    if !t.lately.is_empty() {
        out.push(Stability::Dynamic, format!("\n# Lately, involving {other}\n"));
        for e in t.lately {
            out.push(Stability::Dynamic, format!("- {e}\n"));
        }
    }
    if let Some(e) = t.earlier {
        out.push(Stability::Dynamic, format!("\n# Before this\n{e}\n"));
    }
    out.push(Stability::Dynamic, format!("\n# Now\n{}\n", t.scene));
    if !t.body.is_empty() {
        out.push(Stability::Dynamic, format!("How your body feels: {}\n", t.body));
    }
    for b in t.between {
        out.push(Stability::Dynamic, format!("- {b}\n"));
    }
    out.push(Stability::Dynamic, "\n# The conversation so far\n");
    for l in t.conversation {
        out.push(Stability::Dynamic, format!("{l}\n"));
    }
    out.push(Stability::Dynamic, format!("\n# What you are answering\n{other}: “{}”", t.heard));
    if !t.how.is_empty() {
        out.push(Stability::Dynamic, format!("\n{}", t.how));
    }
    out.render()
}

#[cfg(test)]
mod tests {

    /// The grammar's `doing` example names no skill a reader may never face (a mind copied
    /// "strike" against a foe whose blow is `attack`; r2c): a kind word, and `is` is said to take
    /// what a creature's `visibly`.is shows. Matching is unchanged.
    #[test]
    fn the_doing_example_uses_a_kind_word() {
        let g = grammar();
        let line = g.lines().find(|l| l.contains("{\"doing\":")).expect("the doing condition is in the grammar");
        assert!(line.contains("\"is\": \"hostile\""), "{line}");
        assert!(!line.contains("\"is\": \"strike\""), "{line}");
        assert!(line.contains("what a creature's \"visibly\".is shows in your scene"), "{line}");
    }
    #[test]
    fn the_skill_reference_states_combat_timings() {
        let s = living_rules::script::Scripts::new(include_str!("../../scripts/skills.rhai")).unwrap();
        let t = timings_of(&s);
        assert!(t["strike"].contains("winds up 350 ms") && t["strike"].contains("250 ms to recover") && t["strike"].contains("ready again 650 ms"), "{}", t["strike"]);
        assert!(t["dodge"].starts_with("a dash at once") && t["dodge"].contains("ready again 900 ms"), "{}", t["dodge"]);
        assert!(t["block"].starts_with("raised at once and held up to 8 s"), "{}", t["block"]);
        assert!(t["bowshot"].contains("flies 30 m/s") && t["firebolt"].contains("ready again 4 s"), "{} / {}", t["bowshot"], t["firebolt"]);
        assert!(!t.contains_key("yield") && !t.contains_key("tend") && !t.contains_key("threaten"), "only timed skills: {:?}", t.keys().collect::<Vec<_>>());
        assert!(t.values().all(|w| !w.contains("then 0 ms")), "{t:?}");
        // A character's own moves only, by the techniques it knows; the shared reference has none.
        let archer = own_timings_of(None, |t| t != "fire_bolt");
        assert!(archer.contains("- bowshot: winds up 300 ms") && archer.contains("- strike: winds up 350 ms"), "{archer}");
        assert!(!archer.contains("- firebolt:"), "fire bolt's timing for one who does not know it: {archer}");
        let caster = own_timings_of(None, |_| true);
        assert!(caster.contains("- firebolt: winds up 450 ms"), "{caster}");
        assert!(!skills_help().contains("timing") && !skills_help().contains("winds up 350"), "the shared reference states no timings");
    }

    #[test]
    fn talk_examples_show_every_shown_act() {
        // talk_acts() leaves these out as already shown; a name missing from the examples is an
        // act a conversation turn never offers (host was, until fix-host-example).
        let system = super::talk_system();
        for name in super::TALK_SHOWN {
            assert!(system.contains(&format!("\"do\": \"{name}\"")), "{name} is not shown in the talk turn's examples");
        }
    }

    #[test]
    fn the_body_is_felt_in_words() {
        use super::{felt_body, Body};
        let b = |hp: f32, hunger: f32, energy: f32, hp_rate: f32| felt_body(&Body { hp, max_hp: 100.0, hunger, energy, hp_rate, ..Default::default() });
        assert_eq!(b(100.0, 30.0, 60.0, 0.0), "not hungry, rested, unhurt");
        assert_eq!(b(30.0, 82.0, 8.0, -0.5), "very hungry, exhausted, badly wounded, walking slower; you are growing weaker");
        assert_eq!(b(70.0, 10.0, 90.0, 0.4), "well fed, well rested, a little hurt; your wounds are mending");
        assert_eq!(b(10.0, 99.0, 0.0, -2.0), "starving, your body wasting away, utterly spent, barely alive, walking slower; you are growing weaker");
        assert!(!b(55.0, 60.0, 40.0, 0.0).chars().any(|c| c.is_ascii_digit()));
        // Breath, from the vitals row as the service reads it: out of breath below 20 (after a
        // run or a fight), the status law's words; nothing said above.
        let winded = |s: f64| {
            let row = vec![("hp".to_string(), 100.0), ("max_hp".to_string(), 100.0), ("hunger".to_string(), 30.0), ("energy".to_string(), 60.0), ("at_ms".to_string(), 1000.0),
                           ("stamina".to_string(), s), ("stamina_max".to_string(), 100.0), ("stamina_rate".to_string(), 25.0), ("stamina_from_ms".to_string(), 5000.0)];
            felt_body(&Body { hp: 100.0, max_hp: 100.0, hunger: 30.0, energy: 60.0, row, now_ms: 2000, kind: "person".into(), stage: "adult".into(), ..Default::default() })
        };
        assert!(winded(5.0).contains("out of breath"), "{}", winded(5.0));
        assert!(!winded(60.0).contains("out of breath"), "{}", winded(60.0));
    }

    #[test]
    fn animals_are_told_what_they_smell() {
        let scene = serde_json::json!({"you": {"id": 1}, "creatures": [], living_rules::species::SMELLED: [{"kind": "deer", "id": 7, "dir": "northeast", "dist": "far, about 40 tiles"}]}).to_string();
        let text = super::animal_think_user("Grey", "wolf", "alert", &[], &[], &scene, "hungry");
        assert!(text.contains("You smell a deer to the northeast, far, about 40 tiles."), "{text}");
        assert!(!text.contains(living_rules::species::SMELLED), "{text}");
        let species = living_rules::species::parse(include_str!("../../seeds/species.json")).unwrap();
        let wolf = super::scent_help(&species["wolf"]);
        assert!(wolf.contains("deer, wolf") && wolf.contains("{\"smells\": {\"nearest\": \"deer\"}}"), "{wolf}");
        assert!(super::scent_help(&species["person"]).is_empty());
    }
    use super::*;

    fn context(name: &str) -> Ctx<'_> {
        Ctx {
            name,
            clock: format!("dynamic-clock-{name}"),
            body: String::new(),
            persona: format!("persona-{name}"),
            relations: vec![format!("relation-{name}")],
            mind: vec![format!("dynamic-recall-{name}")],
            memories: vec![format!("dynamic-memory-{name}")],
            judgments: vec![format!("dynamic-stance-{name}")],
            places: vec![format!("place-{name}")],
            experiences: vec![format!("dynamic-experience-{name}")],
            dealings: vec![format!("dynamic-dealing-{name}")],
            cues: None,
        }
    }

    /// The cue field's examples and its schema name no one and no duty: what a mind watches
    /// for is its own (docs/ATTENTION.md).
    #[test]
    fn cue_examples_name_no_one() {
        let field = notice_field_for(600.0, 60.0).to_lowercase();
        let examples = CUE_EXAMPLES.to_lowercase();
        assert!(field.contains(&examples));
        for w in ["stranger", "newcomer", "arriv", "visitor", "outsider", "foreigner", "guest", "intruder", "guard", "keeper", "watchman", "sentry", "gate", "door", "role", "duty", "clerk", "tally", "ledger", "book", "creditor", "debtor", "fisher", "counting"] {
            assert!(!field.contains(w), "the cue field mentions \"{w}\": {field}");
        }
        assert!(!examples.contains("unknown"), "no example watches for people one does not know");
        assert!(field.contains("10 minutes") && field.contains("60 seconds"));
    }

    fn fixture(purpose: &str, name: &str, kind: &str) -> (String, String) {
        fixture_in(purpose, name, kind, Frame::Character)
    }

    fn fixture_in(purpose: &str, name: &str, kind: &str, frame: Frame) -> (String, String) {
        fixture_with(purpose, name, kind, frame, false)
    }

    /// A fixture under a frame, with projects (`LIVING_PROJECTS`) on or off: on, the think and
    /// consolidation system prompts carry the projects text and their user messages a project.
    fn fixture_with(purpose: &str, name: &str, kind: &str, frame: Frame, projects: bool) -> (String, String) {
        let project_lines = if projects { "project:river_camp: a camp by the river (begun day 2)\n" } else { "" };
        static WORLD: std::sync::Once = std::sync::Once::new();
        WORLD.call_once(|| {
            let seed: serde_json::Value = serde_json::from_str(include_str!("../../seeds/world.json")).unwrap();
            let species: serde_json::Value = serde_json::from_str(include_str!("../../seeds/species.json")).unwrap();
            let life = serde_json::from_value(species["person"]["life"].clone()).unwrap();
            set_world(
                seed["setting"].as_str().unwrap_or_default(),
                seed["map"]["w"].as_u64().unwrap_or(96) as u32,
                seed["map"]["h"].as_u64().unwrap_or(96) as u32,
                seed["year_days"].as_f64().unwrap_or(living_rules::YEAR_DAYS as f64) as f32,
                seed["life_pace"].as_f64().unwrap_or(1.0) as f32,
                life,
            );
            set_rules(1, include_str!("../../scripts/skills.rhai"));
        });
        let c = context(name);
        match purpose {
            "think" => (think_system_in(frame, projects), think_user(&c, "dynamic-scene", "dynamic-plan", "dynamic-reason", "habit", project_lines)),
            "deliberate" => (deliberate_system_in(frame), compile_user("dynamic-decision", deliberate_user(&c, "dynamic-scene", "dynamic-outline", "dynamic-plan", "dynamic-reason", "routine"))),
            "consolidate" => (consolidate_system_in(frame, projects), consolidate_user(&c, project_lines)),
            "reorganize" => (reorganize_system(), reorganize_user(name, &c.persona, &["dynamic-concept".into()], &["dynamic-edge".into()], "")),
            "identity" => (identity_system(), identity_user(name, 42, &["fire".into()], &serde_json::json!({"town": "fixture"}), Some(&serde_json::json!({"caution": 40})))),
            "birth_identity" => (birth_identity_system(), birth_identity_user(name, 42, [("Parent A", 3, "kind"), ("Parent B", 4, "gentle")], Some(&serde_json::json!({"caution": 40})))),
            "talk" => (
                talk_system_in(frame),
                talk_user(&TalkUser {
                    name,
                    identity: &c.persona,
                    pacing: "talk slowly",
                    other: if name == "Aria" { "Cora" } else { "Dara" },
                    other_id: if name == "Aria" { 3 } else { 4 },
                    feeling: "friend, trust 50",
                    mind: &c.mind,
                    memories: &c.memories,
                    lately: &c.experiences,
                    earlier: Some("dynamic-earlier"),
                    scene: "dynamic-scene",
                    body: "",
                    conversation: &["dynamic-line".into()],
                    heard: "dynamic-heard",
                    how: "",
                    between: &["dynamic-offer".into()],
                }),
            ),
            "animal_impulse" | "animal_compile" | "animal_consolidate" => {
                let species = living_rules::species::parse(include_str!("../../seeds/species.json")).unwrap();
                let sp = &species[kind];
                match purpose {
                    "animal_impulse" => (animal_think_system(kind, &sp.nature), animal_think_user(name, kind, "temperament", &c.mind, &c.experiences, "dynamic-scene", "dynamic-reason")),
                    "animal_compile" => {
                        let signals = sp.signals.iter().map(|(k, s)| format!("{k} = {}", s.sound)).collect::<Vec<_>>().join("; ");
                        (
                            animal_compile_system(kind, &species_skills_help(sp), &signals, &scent_help(sp), sp.cognition.max_nodes),
                            animal_compile_user(name, kind, "dynamic-impulse", "dynamic-feeling", "dynamic-scene", "dynamic-outline", "routine"),
                        )
                    }
                    _ => (animal_consolidate_system(kind, &sp.nature), consolidate_user(&c, "")),
                }
            }
            _ => panic!("unknown purpose {purpose}"),
        }
    }

    fn assert_prefix(purpose: &str, kind: &str) {
        assert_prefix_in(purpose, kind, Frame::Character);
        if FRAMED.contains(&purpose) {
            assert_prefix_in(purpose, kind, Frame::Player);
        }
    }

    /// The prompts `LIVING_FRAME` reaches.
    const FRAMED: [&str; 4] = ["think", "deliberate", "consolidate", "talk"];

    fn assert_prefix_in(purpose: &str, kind: &str, frame: Frame) {
        assert_prefix_with(purpose, kind, frame, false)
    }

    fn assert_prefix_with(purpose: &str, kind: &str, frame: Frame, projects: bool) {
        let (system_a, user_a) = fixture_with(purpose, "Aria", kind, frame, projects);
        let (system_b, user_b) = fixture_with(purpose, "Zora", kind, frame, projects);
        assert_eq!(system_a.as_bytes(), system_b.as_bytes());
        assert!(!system_a.contains("Aria") && !system_a.contains("Zora"));
        let a = format!("{system_a}\n{user_a}");
        let b = format!("{system_b}\n{user_b}");
        let shared_user = if purpose == "talk" {
            "Your turn. Respond with the JSON object.\n\n"
        } else if matches!(purpose, "think" | "deliberate" | "consolidate" | "reorganize" | "animal_consolidate") {
            "Respond with the JSON object.\n\n"
        } else {
            ""
        };
        let shared_len = system_a.len() + 1 + shared_user.len();
        assert!(user_a.starts_with(shared_user) && user_b.starts_with(shared_user));
        assert_eq!(&a.as_bytes()[..shared_len], &b.as_bytes()[..shared_len]);
        let lcp = a.bytes().zip(b.bytes()).take_while(|(a, b)| a == b).count();
        assert!(lcp >= shared_len, "{purpose}/{kind}: {lcp} < {shared_len}");
        for text in [&a, &b] {
            let character = text.find(if text == &a { "Aria" } else { "Zora" }).unwrap();
            assert!(character >= shared_len);
            for (pos, _) in text.match_indices("dynamic-") {
                assert!(pos > character, "{purpose}/{kind}: dynamic content precedes identity");
            }
            for stable in ["place-", "# Your habits", "# Your routines", "Its routines"] {
                if let Some(pos) = text.find(stable) {
                    assert!(pos < text.find("dynamic-").unwrap(), "{purpose}/{kind}: {stable} follows dynamic content");
                }
            }
        }
    }

    #[test]
    fn think_shares_prefix() {
        assert_prefix("think", "person");
    }
    #[test]
    fn deliberate_shares_prefix() {
        assert_prefix("deliberate", "person");
    }
    #[test]
    fn consolidate_shares_prefix() {
        assert_prefix("consolidate", "person");
    }
    #[test]
    fn reorganize_shares_prefix() {
        assert_prefix("reorganize", "person");
    }
    #[test]
    fn body_line_says_age_stage_and_how_long() {
        // Cullet's lives on the hamlet's pace: 90 years, a year of 4 days at pace 0.0357 (0.143
        // world days), adult from 15 years, old from 59.5.
        let life = living_rules::life::Life { years: 90.0, infant: 2.0 / 90.0, child: 15.0 / 90.0, elder: 59.5 / 90.0, ..Default::default() };
        let pace = living_rules::life::Pace { year_days: 4.0, pace: 0.0357 };
        let year = 4.0 * 0.0357;
        assert_eq!(body_line_of("person", 2, 15.05 * year, life, pace), "Your body: 15 years old, an adult for a few hours.");
        assert_eq!(body_line_of("person", 1, 14.9 * year, life, pace), "Your body: 14 years old, a child for 12 years.");
        assert_eq!(body_line_of("person", 2, 41.0 * year, life, pace), "Your body: 41 years old, an adult for 26 years.");
        assert_eq!(body_line_of("person", 3, 60.0 * year, life, pace), "Your body: 60 years old, old for a few hours.");
        assert_eq!(body_line_of("person", 0, 0.01, life, pace), "Your body: less than a year old, a baby for a few hours.");
        assert_eq!(body_line_of("wolf", 2, 15.5 * year, life, pace), "Your body: 15 years old, grown for a few hours.");
    }

    #[test]
    fn identity_shares_prefix() {
        assert_prefix("identity", "person");
        assert_prefix("birth_identity", "person");
    }
    #[test]
    fn talk_shares_prefix() {
        assert_prefix("talk", "person");
    }
    #[test]
    fn animal_impulse_shares_prefix() {
        for kind in ["wolf", "deer"] {
            assert_prefix("animal_impulse", kind);
        }
    }
    #[test]
    fn animal_compile_shares_prefix() {
        for kind in ["wolf", "deer"] {
            assert_prefix("animal_compile", kind);
        }
    }
    #[test]
    fn animal_consolidate_shares_prefix() {
        for kind in ["wolf", "deer"] {
            assert_prefix("animal_consolidate", kind);
        }
    }

    #[test]
    fn frame_parses() {
        assert_eq!(Frame::parse(None), Ok(Frame::Character));
        assert_eq!(Frame::parse(Some("")), Ok(Frame::Character));
        assert_eq!(Frame::parse(Some("character")), Ok(Frame::Character));
        assert_eq!(Frame::parse(Some("player")), Ok(Frame::Player));
        assert!(Frame::parse(Some("Player")).is_err() && Frame::parse(Some("npc")).is_err());
    }

    /// Without `LIVING_FRAME` the service runs the character frame, and the character frame is
    /// the prompts as they read before the switch: each opens with its old first sentence and
    /// carries nothing of the player frame. (Byte identity with the prompts before the switch was
    /// checked by exporting every fixture before and after, `export_prompt_fixtures`.)
    #[test]
    fn character_frame_is_the_default_and_unchanged() {
        if std::env::var_os("LIVING_FRAME").is_none() && std::env::var_os("LIVING_PROJECTS").is_none() {
            assert_eq!(frame(), Frame::Character);
            fixture("think", "Aria", "person");
            assert_eq!(think_system(), think_system_in(Frame::Character, false));
            assert_eq!(deliberate_system(), deliberate_system_in(Frame::Character));
            assert_eq!(consolidate_system(), consolidate_system_in(Frame::Character, false));
            assert_eq!(talk_system(), talk_system_in(Frame::Character));
        }
        for (purpose, first) in [
            ("think", "You are the mind of the person described under # Who you are, living in a persistent simulated world. Stay in character: "),
            ("deliberate", "You are the mind of the person described under # Who you are, living in a persistent simulated world. Stay in character: "),
            ("consolidate", "You are the memory and self-understanding of the person described under # Who you are, in a persistent simulated world. You keep "),
            ("talk", "You are the person described under # Who you are, living in a persistent world, face to face with the other person described below. This is your turn "),
        ] {
            let (system, user) = fixture(purpose, "Aria", "person");
            assert!(system.starts_with(first), "{purpose}: {}", &system[..160]);
            let text = format!("{system}\n{user}");
            for frame_word in ["AI playing", "other players", "out of character", PLAYER_FRAME] {
                assert!(!text.contains(frame_word), "{purpose}: the character frame carries {frame_word:?}");
            }
        }
    }

    /// Under the player frame a framed prompt opens with `PLAYER_FRAME`, and nothing but its
    /// opening sentence differs: the rules, grammar, reply shapes and every user message are the
    /// character frame's.
    #[test]
    fn player_frame_changes_only_the_opening() {
        for (purpose, character_opening) in [("think", THINK_OPENING), ("deliberate", THINK_OPENING), ("consolidate", CONSOLIDATE_OPENING), ("talk", TALK_OPENING)] {
            let (cs, cu) = fixture_in(purpose, "Aria", "person", Frame::Character);
            let (ps, pu) = fixture_in(purpose, "Aria", "person", Frame::Player);
            assert!(ps.starts_with(PLAYER_FRAME), "{purpose}");
            assert_eq!(pu, cu, "{purpose}: the user message changed");
            assert_eq!(ps.replacen(&opening(Frame::Player, character_opening), character_opening, 1), cs, "{purpose}");
            assert!(ps.contains("never speak out of character"), "{purpose}");
        }
    }

    /// `LIVING_FRAME=player` and `LIVING_PROJECTS=1` together: each does exactly what it does
    /// alone. The frame replaces only the opening sentence; the projects text, the `serves`
    /// field and the projects section stay as projects alone has them.
    #[test]
    fn player_frame_and_projects_compose() {
        for (purpose, character_opening, projects_text) in [
            ("think", THINK_OPENING, THINK_PROJECTS),
            ("deliberate", THINK_OPENING, ""),
            ("consolidate", CONSOLIDATE_OPENING, CONSOLIDATE_PROJECTS),
            ("talk", TALK_OPENING, ""),
        ] {
            let (both_s, both_u) = fixture_with(purpose, "Aria", "person", Frame::Player, true);
            let (proj_s, proj_u) = fixture_with(purpose, "Aria", "person", Frame::Character, true);
            let (frame_s, frame_u) = fixture_with(purpose, "Aria", "person", Frame::Player, false);
            assert!(both_s.starts_with(PLAYER_FRAME), "{purpose}");
            // Without its frame opening, both-on is projects alone.
            assert_eq!(both_s.replacen(&opening(Frame::Player, character_opening), character_opening, 1), proj_s, "{purpose}");
            assert_eq!(both_u, proj_u, "{purpose}: the frame changed a user message");
            // Without the projects text, both-on is the frame alone.
            if !projects_text.is_empty() {
                assert!(both_s.contains(projects_text), "{purpose}: projects text missing");
                assert_eq!(both_s.replacen(projects_text, "", 1), frame_s, "{purpose}");
                assert!(both_u.contains("# Your projects") && both_u.contains("project:river_camp"), "{purpose}");
                assert!(!frame_u.contains("# Your projects"), "{purpose}");
            } else {
                assert_eq!(both_s, frame_s, "{purpose}");
                assert_eq!(both_u, frame_u, "{purpose}");
            }
        }
        assert!(THINK_PROJECTS.contains("\"serves\""));
        for purpose in FRAMED {
            assert_prefix_with(purpose, "person", Frame::Player, true);
        }
    }

    /// The frame says who plays and what is real, and leaves what to do to the player.
    #[test]
    fn player_frame_is_short_and_prescribes_nothing() {
        assert!(PLAYER_FRAME.split_whitespace().count() <= 80, "{PLAYER_FRAME}");
        let lower = PLAYER_FRAME.to_lowercase();
        for word in ["goal", "explore", "interesting", "adventure", "reputation", "risk", "should", "must", "surviv", "quest"] {
            assert!(!lower.contains(word), "the frame prescribes: {word}");
        }
        for needed in ["AI playing", "other players, human and AI", "body, needs and death are real", "world's rules hold", "your own choice", "says or writes", "out of character"] {
            assert!(PLAYER_FRAME.contains(needed), "the frame lacks {needed:?}");
        }
    }

    #[test]
    fn segments_order_by_stability() {
        let mut out = Segments::default();
        out.push(Stability::Dynamic, "clock");
        out.push(Stability::Character, "persona");
        out.push(Stability::Shared, "rules");
        out.push(Stability::Character, "places");
        assert_eq!(out.render(), "rulespersonaplacesclock");
    }

    #[test]
    fn the_grammar_says_what_stranger_means_under_the_law_in_force() {
        // The shipped rules (the law off): no feelings yet; the law on says names, and the two differ.
        let (system, _) = fixture("deliberate", "Aria", "person");
        assert!(system.contains(&format!("stranger {}", stranger_words_for(false))), "{system}");
        assert!(!system.contains(stranger_words_for(true)));
        let on = living_rules::script::with_world_laws(include_str!("../../scripts/skills.rhai"), &[("stranger_by_name".into(), serde_json::json!(true))]);
        assert!(living_rules::script::Scripts::new(&on).unwrap().laws().stranger_by_name);
    }

    #[test]
    fn export_prompt_fixtures() {
        let Ok(dir) = std::env::var("LIVING_PROMPT_FIXTURES") else { return };
        let dir = std::path::Path::new(&dir);
        std::fs::create_dir_all(dir).unwrap();
        for purpose in ["think", "deliberate", "consolidate", "reorganize", "identity", "birth_identity", "talk", "animal_impulse", "animal_compile", "animal_consolidate"] {
            for kind in if purpose.starts_with("animal_") { vec!["wolf", "deer"] } else { vec!["person"] } {
                for name in ["Aria", "Zora"] {
                    let frames: &[Frame] = if FRAMED.contains(&purpose) { &[Frame::Character, Frame::Player] } else { &[Frame::Character] };
                    for &frame in frames {
                        let (system, user) = fixture_in(purpose, name, kind, frame);
                        let body = serde_json::json!({"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]});
                        let tag = if frame == Frame::Character { String::new() } else { format!("-{}", frame.name()) };
                        std::fs::write(dir.join(format!("{purpose}-{kind}-{name}{tag}.json")), serde_json::to_string_pretty(&body).unwrap()).unwrap();
                    }
                }
            }
        }
    }
}
