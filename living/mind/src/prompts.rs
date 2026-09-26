//! Prompt construction. Context is assembled only from the character's own persona,
//! relations, beliefs, judgments, places, episodes and the scene it currently perceives.


const RULES: &str = "\
One day lasts 12 real minutes; night is 20:00-06:00 and cuts sight to 6 tiles (11 by day).
SEASONS_LINE
BODY: hunger rises ~5/min (100 = starving, which drains health); energy falls ~3/min awake and recovers while sleeping (faster within 2 tiles of a shelter). \
At night, people farther than 3 tiles from a campfire and 2 from a shelter or house, and without a warm cloak, lose health to the cold. Health recovers slowly when fed and rested. Death is permanent.
KNOW-HOW: you can only do techniques you know: fire (campfire), cooking, spear, shelter, storage, cloak (2 hides from hunted deer + 1 fiber; keeps you warm at night), \
torch (lights the night, you see farther), planting (grow new berry bushes), writing (write and read tablets and signs), \
masonry (walls), carpentry (houses and gates; needs shelter), toolmaking (axe, pick). Others may know what you don't: \
ask them to teach you (teach takes time beside each other), read what someone wrote, or experiment with materials to work something out yourself. \
What only one person knows dies with them unless they teach it or write it down.
FOOD: berries 12, raw fish 16, raw meat 20, cooked fish 34, cooked meat 42 (hunger points). Cook raw fish/meat at a campfire (needs cooking). \
Berry bushes, reeds, fishing spots, trees, boulders and clay banks (along rivers) regrow slowly after harvesting; stone is plentiful in the western hills and scarce in the east. Deer can be hunted (3 meat); wolves roam forests, hunt deer and attack people at night when hungry.
MAKING: campfire = 3 wood, shelter = 6 wood + 3 fiber, storage = 4 wood (anyone can take from a storage), spear = 2 wood + 1 stone (hits much harder, faster fishing), \
cloak = 2 hide + 1 fiber, torch = 1 wood + 1 fiber, tablet or sign = 1 wood (write), \
house = 6 wood + 4 clay + 2 stone (a home: warm like a shelter and a fire), gate = 4 wood, wall = 2 stone per tile, road = 1 stone per tile (pave where you stand; walking on road is faster), \
axe = 2 wood + 1 stone (cut wood twice as fast), pick = 2 wood + 2 stone (break stone twice as fast).
SETTLEMENTS: walls block the way; a gate lets people through while open, and only the members of the community that keeps it may open or shut it. \
Who is let in, when gates are shut and who keeps watch is for each community to decide.
LIFE_LINE
COMBAT: fights are fast. An attack winds up for about 0.6-0.75 s before it lands; the target can see it coming \
({\"threatened\": true}). dodge = a quick dash (an attack landing during it misses; costs energy); block = raise your guard \
(hits do a quarter of the damage, but you cannot act meanwhile); throw = hurl your spear up to 7 tiles (you lose it). \
A blow lands only if you are still within reach (about 2 tiles; a wolf's leap about 3) when its windup ends: stepping back or running as it winds up makes it miss, \
but whoever swings stands still meanwhile. People run 2.6 tiles/s, wolves 3.4, grown deer 3.7 (a wolf catches the young, old, tired or surprised): you can outrun a person who keeps stopping to swing, not a wolf. \
While fighting, your graph is checked about 15 times a second; you can patch a single labeled branch mid-fight.
COMMUNITIES: people can found a community (the act {\"do\": \"found\", \"text\": \"its name\"}), ask a member to join it (join), welcome someone who asked (welcome), or leave. What a community means, who does what and how it treats others is up to its members.
TIME: beyond staying alive, how you spend your days is yours to decide, from who you are and what you want.
OTHERS: people hear speech within ~9 tiles. You cannot read minds; what others say may be false. You only know what you perceived or were told.";

static SETTING: std::sync::OnceLock<String> = std::sync::OnceLock::new();
static SIZE: std::sync::OnceLock<(u32, u32)> = std::sync::OnceLock::new();

/// The world's size in tiles (from the active seed).
pub fn map_size() -> (u32, u32) {
    SIZE.get().copied().unwrap_or((96, 96))
}

/// Set once at startup from the active seed: its setting text and map size.
/// Set once at startup from the active seed: setting, map size, calendar and the people's life table.
pub fn set_world(setting: &str, w: u32, h: u32, year_days: f32, pace: f32, life: living_rules::life::Life) {
    let _ = SIZE.set((w, h));
    let season_days = year_days / 4.0;
    let seasons = format!(
        "SEASONS: a year is {} days — spring, summer, autumn, winter ({} each). In winter nothing regrows and nights are colder: store food before it.",
        year_days.round(),
        living_rules::describe_days(season_days)
    );
    let years = |f: f32| (f * life.years).round();
    let t = living_rules::life::Pace { year_days, pace };
    let life_line = format!(
        "LIFE: a person lives about {} years (a year is {} days): a baby until about {}, a child until about {}, old from about {}. \
Babies cannot walk far or feed themselves; they cry when hungry, cold or alone. Children are slow, cannot build, craft or fight, and depend on others. \
Old people tire sooner and heal slower. Two adults who both choose to start a family (the act `conceive` toward each other) within two minutes, while fed, have a child about {} later.",
        life.years.round(),
        year_days.round(),
        years(life.infant),
        years(life.child),
        years(life.elder),
        living_rules::describe_days(life.gestation_days(t))
    );
    let rules = RULES.replace("SEASONS_LINE", &seasons).replace("LIFE_LINE", &life_line);
    let _ = SETTING.set(format!("WORLD: {setting} Coordinates are tiles (x east, y south, map {w}x{h}); walking covers about 3 tiles a second.\n{rules}"));
}

/// The world's rules as every mind is told them.
pub fn world_rules() -> &'static str {
    SETTING.get().map(|s| s.as_str()).unwrap_or(RULES)
}

pub fn grammar() -> String {
    grammar_with(&living_rules::catalog::skills_help(), true)
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
    let g = format!(
        "\
BEHAVIOR GRAPH (JSON) — it runs continuously (~1 check per second, instantly on events) while you think slowly, so encode how to react, not just one action.
Nodes:
- {{\"first\": [N, ...]}} priority: every check, the first child that is running or succeeds wins; higher children interrupt lower ones. Optional label: {{\"first\": [...], \"label\": \"...\"}}.
- {{\"seq\": [N, ...]}} steps in order, remembering progress; fails when a step fails.
- {{\"if\": C, \"then\": N, \"else\": N}} guard (else optional): the branch runs only while C holds, except that work already begun under it (sleep, rest, eat, gather, build, craft, cook, teach, write, read, plant...) is finished; walking, fleeing and fighting stop as soon as C no longer holds.
- {{\"do\": \"skill\", \"target\": T, \"item\": \"...\", \"qty\": n}} perform a skill (target/item/qty only when needed); walks to the target first automatically.{making}
- {{\"say\": \"text\", \"to\": T}} speak (each say node speaks at most once per 45 s).
- {{\"wait\": seconds}}
- {{\"think\": \"reason\"}} ask yourself to reconsider (non-blocking; ignored within 45 s of a decision, then at most once per 90 s). Put it where your plan runs out (e.g. last in a seq or as the final fallback), not where it is reached on every check.
Several conditions in one object mean all of them: {{\"if\": {{\"hunger\": {{\"above\": 60}}, \"has\": {{\"item\": \"food\"}}}}, \"then\": {{\"do\": \"eat\", \"item\": \"food\"}}}}
Conditions C: {{\"hunger\": {{\"above\": 60}}}} {{\"energy\": {{\"below\": 25}}}} {{\"health\": {{\"below\": 40}}}} (0-100)
  {{\"has\": {{\"item\": \"berries\", \"at_least\": 2}}}} (item \"food\" = any food) {{\"sees\": T}} {{\"near\": {{\"target\": T, \"within\": 3}}}}
  {{\"count\": {{\"of\": \"wolf\" or {{\"kind\": \"person\", \"relation\": \"friend\"}}, \"within\": 8, \"at_least\": 3}}}} (or \"at_most\") how many are in sight; {{\"health_of\": {{\"target\": T, \"below\": 30}}}} how healthy a creature in sight is (% of full)
  {{\"hurt_within\": 10}} {{\"heard_within\": 20}} {{\"threatened\": true}} {{\"night\": true}} {{\"believes\": \"judgment_key\"}} or {{\"believes\": {{\"key\": \"k\", \"above\": 0.7}}}}
  {{\"chance\": 0.2}} {{\"all\": [C, ...]}} {{\"any\": [C, ...]}} {{\"not\": C}}
Targets T: \"self\" \"attacker\" \"speaker\" \"suitor\" (who just offered to start a family with you) \"partner\" (the other parent of your youngest child) \"home\" {{\"nearest\": \"berry_bush\"}} {{\"nearest\": {{\"kind\": \"person\", \"relation\": \"friend\"}}}} (relation: friend|enemy|stranger|family, or any label you gave a relationship, e.g. partner)
  {{\"nearest\": {{\"kind\": \"storage\", \"mine\": true}}}} {{\"id\": 6}} {{\"named\": \"Oren\"}} {{\"place\": \"name of a place you remember\"}} {{\"at\": [x, y]}}
  Kinds: berry_bush tree boulder reeds fishing_spot clay_bank | campfire shelter house storage sign gate remains | person deer wolf.
  People/creature/resource targets resolve only when currently in sight; places and coordinates always resolve. A do-node whose target is missing fails, so \"first\" moves on.
Skills:
{}
- {{\"routine\": \"name\"}} runs one of your routines (named graphs you keep; see below).
- {{\"desires\": [{{\"want\": \"what it is for\", \"weight\": W, \"do\": N}}, ...]}} every check, the strongest desire that can act now wins (a desire whose node fails lets the next one act). \
W = {{\"base\": number, and any of: \"hunger\", \"tired\", \"hurt\", \"night\", \"day\", \"threatened\", \"alone\", \"company\", \"winter\", \"longing\", \"courted\": factor, \"believes\": {{\"stance_key\": factor}}}}: \
strength = base + Σ factor × signal, each signal 0..1 (hunger 0 fed..1 starving; tired 0 rested..1 exhausted; hurt; night/day; threatened = an attack is coming; \
alone = no one in sight; company = people in sight; winter; longing = time since this desire last acted, up to an hour; courted = someone in sight just offered to start a family with you; believes = your stance's value). A desire at or below 0 does not act.
Limits: each graph (your top level, or one routine) at most 64 nodes, depth 10, 12 children per composite. The root restarts whenever it finishes, so a root \"first\" loops forever.
REPERTOIRE: your behavior is a repertoire you build over your life: routines (named graphs) for the things you do, called from a top level, usually desires weighed by what you want. \
Refine one routine at a time as you learn what works (each routine shows how it has gone: successes, failures and why); make new ones for new things; retire what you no longer do. \
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
While an act is under way your graph's work waits; only its reflexes (flee, dodge, block, attack, throw) break it off. \
Forms: {\"do\": \"conceive\", \"target\": {\"id\": 6}} (start a family: it happens when you both choose it toward each other within two minutes), \
{\"do\": \"give\", \"target\": {\"id\": 4}, \"item\": \"berries\", \"qty\": 3}, \
{\"do\": \"offer\", \"target\": {\"id\": 4}, \"item\": \"fish\", \"qty\": 2, \"want\": \"wood\", \"want_qty\": 3}, {\"do\": \"accept\", \"target\": {\"id\": 4}} (take a trade offered to you), \
{\"do\": \"teach\", \"target\": {\"id\": 6}, \"item\": \"fire\"}, {\"do\": \"tend\", \"target\": {\"id\": 6}}, \
{\"do\": \"write\", \"item\": \"tablet\"|\"sign\", \"text\": \"your words\", \"topic\": \"a technique you know\"}, {\"do\": \"read\"}, \
{\"do\": \"join\"|\"welcome\", \"target\": {\"id\": 6}}, {\"do\": \"found\", \"text\": \"a name\"}, and any other single piece of work (build, craft, cook, store, take, plant). \
A single walk ({\"do\": \"goto\", \"target\": T}) can be a step before an act (e.g. goto a place, then build there); \
following, fleeing, fighting, sleeping and resting are not acts: they are your graph. Words change nothing in the world by themselves: \
if you agree to do something now, do it as an act.";

/// Thinking: the decision itself, as the person, without the body's grammar (which crowds out
/// the choices of a life: in replays of real moments, 2 in 12 minds acted on a longing for a
/// child with the grammar in view, 11 in 12 without it).
pub fn think_system(name: &str) -> String {
    format!(
        "You are the mind of {name}, a person living in a persistent simulated world. Stay in character: your personality, values, relationships and memories are yours, \
and they may change through what you live. Start from why you are thinking now: that is what this moment of thought is about. \
Think about it as {name}: what you make of it, and what you mean to do. Your body keeps to its habits on its own (eating, sleeping, keeping warm, \
staying safe, your work) unless you decide otherwise, so decide what this moment calls for, not everything. \
Speech is how you share yourself: what you think, feel, remember, hope or suspect, as well as practical matters; you may also stay silent. \
Refer to people by the ids you see. Do not assume facts you have not perceived.\n\n{}\n\n\
Reply with ONE JSON object: {{\"thought\": \"what you make of this moment (1-3 sentences)\", \
\"intend\": [\"each thing you mean to do, in plain words, in order (e.g. ask Borno (#5) to start a family with me; give Galy (#8) 2 berries; \
relight the fire; from now on keep watch at night)\"] (may be empty), \
\"say\": {{\"text\": \"...\", \"to\": id or null}} or null, \
\"judgments\": [{{\"key\": \"snake_case\", \"value\": 0.0-1.0, \"why\": \"...\"}}] (optional stances), \
\"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}] (optional places worth remembering)}}",
        world_rules()
    )
}

pub fn think_user(c: &Ctx, scene: &str, plan: &str, reason: &str, habits: &str) -> String {
    let mut out = format!("# Why you are thinking now\n{reason}\n\n");
    common(c, &mut out);
    out.push_str("\n# Recent experiences (oldest first)\n");
    for e in &c.experiences {
        out.push_str(&format!("- {e}\n"));
    }
    out.push_str(&format!("\n# What you perceive right now\n{scene}\n"));
    out.push_str(&format!("\n# What you were doing\n{plan}\n\n# Your habits (your body keeps to them)\n{habits}\n"));
    out.push_str("\nRespond with the JSON object.");
    out
}

/// Compiling: the body's expression of a decision already made (acts now, an intent over time).
pub fn compile_user(decision: &str, deliberate: &str) -> String {
    format!("# What you decided (express exactly this: add nothing, drop nothing)\n{decision}\n\n{deliberate}")
}

pub fn deliberate_system(name: &str) -> String {
    format!(
        "You are the mind of {name}, a person living in a persistent simulated world. Stay in character: your personality, values, relationships and memories are yours, \
and they may change through what you live. {name} has already decided what to do (see What you decided): express that decision as deliberate acts to carry out now (in order) and, for what goes on over time, an intent weighed among your desires, or routine changes. Don't add intentions of your own or drop any; leave speech to the decision.\n\n{}\n\n{}\n\n{}\n\n\
A graph can span a whole day: hour conditions ({{\"hour\": {{\"above\": 6, \"below\": 12}}}}) let you do different things at different times. \
Speech is how you share yourself: what you think, feel, remember, hope or suspect, what you make of the other person, as well as \
practical matters. Talk as the person you are, in your own voice; you may also stay silent, deflect or lie. Don't just echo what was \
already agreed. \
Your top level and your routines are all your body does: they began as your habits, and they are yours to keep, change or drop; \
nothing eats, sleeps or keeps you warm unless they do. Change what needs changing: a routine, the top level, or both. \
Refer to people by the ids you see. Do not assume facts you have not perceived. Reply with ONE JSON object:\n\
{{\"thought\": \"your private interpretation of the situation (1-3 sentences)\", \"say\": {{\"text\": \"...\", \"to\": id or null}} or null, \
\"acts\": [ACTS to carry out now, in order] (optional), \
\"plan\": \"one-line intention\", \"intent\": {{\"weight\": 0.1-1.5, \"graph\": {{...what you mean to do...}}}} (becomes your routine \"current plan\", \
weighed among your desires as \"the plan\": needs keep their own pull, e.g. strong hunger ≈ 1.0, so a plan of 0.6 yields to it and resumes after), \
\"graph\": \"keep\", or a new top level {{...}} with \"restructure\": true only to change how you live (what you weigh and how; without it a graph counts as your intent), \
\"routines\": [{{\"name\": \"...\", \"graph\": {{...}}}} to add or replace a routine, or {{\"name\": \"...\", \"retire\": true}}] (optional; a few at a time), \
or instead of graph \"patch\": {{\"label\": \"combat\", \"graph\": {{...}}}} to replace only that labeled branch (e.g. adapt how you fight mid-fight) and keep the rest, \
\"judgments\": [{{\"key\": \"snake_case\", \"value\": 0.0-1.0, \"why\": \"...\"}}] (optional stances your graph can test with believes), \
\"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}] (optional places worth remembering, e.g. home, good berry patch)}}",
        world_rules(),
        grammar(),
        ACTS
    )
}

pub fn consolidate_system(name: &str) -> String {
    format!(
        "You are the memory and self-understanding of {name}, a person in a persistent simulated world. \
You keep {name}'s mind as a graph that you shape freely: concepts (people, places, things, ideas, plans, fears, customs, promises...) \
and relationships between them, named in your own words (any labels, any relationship names, any properties). \
Integrate the new experiences: record what {name} now takes to be true, feels, intends or suspects. It may be wrong; \
hearsay stays hearsay (e.g. person:4 -CLAIMED-> idea:wolves_at_ford). Don't transcribe routine: capture meaning, patterns and \
changes. Above all, REVISE: check the existing mind for anything these experiences contradict, weaken, strengthen or make \
outdated, and change it — re-assert an edge with a new confidence, retract what is no longer held, give a concept the labels \
that fit it now (labels you give REPLACE its old ones, e.g. a Stranger who became a Friend), clear a property with null, and \
merge concepts that turn out to be the same thing. Prefer connecting to existing concepts over inventing new ones. \
History is kept automatically. Keep as memories only the \
few experiences {name} would still remember tomorrow (at most 3, often none), each with a gist in {name}'s own words. Identity (narrative, values, goals, traits 0-100, \
mood) changes only when experiences genuinely warrant it; otherwise identity is null.\n\n{}\n\n\
KEYS: anchors connect your mind to the world: \"self\", \"person:<numeric id>\" (e.g. \"person:7\", never a name), \"place:<name>\", \"kind:<wolf|deer|berry_bush|campfire|...>\". \
Any other key is yours to invent (\"idea:shared_storage\", \"plan:river_camp\"). Reuse existing keys shown in your mind.\n\
The body acts on three parts of the mind without thinking: how {name} feels about people (self -FEELS {{trust, affinity -100..100, label, note}}-> person:<id>), \
stances the behavior graph can test (self -JUDGES {{value 0..1, why}}-> stance:<key>, e.g. stance:wolves_hunt_near_camp; stances relax toward 0.5 unless reinforced) \
and places with coordinates (place:<name> with props x, y). You can write those edges directly, or use the shorthand arrays below \
(relations, judgments, places), which become exactly those edges. Keep stance keys stable.\n\n\
Reply with ONE JSON object:\n\
{{\"summary\": \"what this meant to {name} (1-2 sentences)\",\n\
 \"remember\": [{{\"exp\": experience id, \"gist\": \"...\"}}],\n\
 \"nodes\": [{{\"key\": \"person:4\", \"labels\": [\"Person\", \"Rival\"], \"name\": \"Bram\", \"props\": {{...}}}}],\n\
 \"edges\": [{{\"from\": \"person:4\", \"rel\": \"TOOK_FOOD_FROM\", \"to\": \"place:our_storage\", \"confidence\": 0.0-1.0, \"because\": [experience ids], \"props\": {{...}}}}],\n\
 \"retract\": [{{\"from\": \"self\", \"rel\": \"TRUSTS\", \"to\": \"person:4\"}}],\n\
 \"merge\": [{{\"from\": \"idea:kael_seems_kind\", \"into\": \"idea:kael_is_friendly\"}}],\n\
 \"relations\": [{{\"id\": person id, \"trust\": 0, \"affinity\": 0, \"label\": \"friend|family|partner|ally|rival|enemy|stranger|...\", \"note\": \"short\"}}],\n\
 \"judgments\": [{{\"key\": \"...\", \"value\": 0.0-1.0, \"why\": \"...\"}}],\n\
 \"places\": [{{\"name\": \"...\", \"x\": 0, \"y\": 0}}],\n\
 \"identity\": null or {{\"narrative\": \"first person, 2-4 sentences\", \"values\": [...], \"goals\": [...], \"traits\": {{...}}, \"mood\": \"...\", \"why\": \"what changed\"}}}}",
        world_rules()
    )
}

pub fn reorganize_system(name: &str) -> String {
    format!(
        "You are the mind of {name}, resting. Tidy {name}'s mind the way sleep does, without inventing anything new that happened: \
merge concepts that are really the same thing (keep the clearer key), generalize repeated specifics into lasting patterns and then retract \
the specifics (e.g. many SAW edges to kind:wolf → one pattern such as kind:wolf -HUNTS_NEAR-> place:ford), relabel concepts whose role \
changed, retract what {name} no longer holds or that no longer matters, and strengthen what keeps proving true. Aim for a smaller, \
better connected mind that still contains everything {name} cares about. Anchor keys (self, person:<id>) cannot be merged away.\n\n\
Reply with ONE JSON object: {{\"summary\": \"how {name}'s understanding settled (1-2 sentences)\", \
\"merge\": [{{\"from\": key, \"into\": key}}], \"nodes\": [{{\"key\": ..., \"labels\": [...], \"name\": ..., \"props\": {{...}}}}], \
\"edges\": [{{\"from\": key, \"rel\": \"...\", \"to\": key, \"confidence\": 0.0-1.0, \"because\": [experience ids from the edges you generalize]}}], \
\"retract\": [{{\"from\": key, \"rel\": \"...\", \"to\": key}}], \"judgments\": [{{\"key\": ..., \"value\": 0.0-1.0, \"why\": ...}}]}}"
    )
}

pub fn reorganize_user(persona: &str, concepts: &[String], edges: &[String]) -> String {
    let mut out = format!("# Who you are\n{persona}\n\n# Your concepts (key \"name\" [labels] {{properties}} — links)\n");
    for c in concepts {
        out.push_str(&format!("- {c}\n"));
    }
    out.push_str("\n# Your current beliefs and links (strength after fading, when last reinforced)\n");
    for e in edges {
        out.push_str(&format!("- {e}\n"));
    }
    out.push_str("\nRespond with the JSON object.");
    out
}

pub struct Ctx<'a> {
    pub name: &'a str,
    pub clock: String,
    pub persona: String,
    pub relations: Vec<String>,
    pub mind: Vec<String>,
    pub memories: Vec<String>,
    pub judgments: Vec<String>,
    pub places: Vec<String>,
    pub experiences: Vec<String>,
}

fn common(c: &Ctx, out: &mut String) {
    out.push_str(&format!("# Who you are ({}), now {}\n{}\n", c.name, c.clock, c.persona));
    out.push_str("\n# People you know\n");
    if c.relations.is_empty() {
        out.push_str("(nobody yet)\n");
    }
    for r in &c.relations {
        out.push_str(&format!("- {r}\n"));
    }
    out.push_str("\n# What comes to mind (recalled by what you perceive, what is happening and why; what you hold true, feel and intend; keys in parentheses)\n");
    if c.mind.is_empty() {
        out.push_str("(nothing yet)\n");
    }
    for f in &c.mind {
        out.push_str(&format!("- {f}\n"));
    }
    if !c.memories.is_empty() {
        out.push_str("\n# Memories this brings back\n");
        for m in &c.memories {
            out.push_str(&format!("- {m}\n"));
        }
    }
    out.push_str("\n# Your stances on your mind now (usable as {\"believes\": key})\n");
    if c.judgments.is_empty() {
        out.push_str("(none)\n");
    }
    for j in &c.judgments {
        out.push_str(&format!("- {j}\n"));
    }
    out.push_str("\n# Places you remember\n");
    if c.places.is_empty() {
        out.push_str("(none)\n");
    }
    for p in &c.places {
        out.push_str(&format!("- {p}\n"));
    }
}

pub fn deliberate_user(c: &Ctx, scene: &str, graph_outline: &str, plan: &str, reason: &str, repertoire: &str) -> String {
    // Why this thought happens comes first: it is what the moment of thought is about.
    let mut out = format!("# Why you are thinking now\n{reason}\n\n");
    common(c, &mut out);
    out.push_str("\n# Recent experiences (oldest first)\n");
    for e in &c.experiences {
        out.push_str(&format!("- {e}\n"));
    }
    out.push_str(&format!("\n# What you perceive right now\n{scene}\n"));
    out.push_str(&format!("\n# Your top level (plan: {plan})\n{graph_outline}\n"));
    if !repertoire.is_empty() {
        out.push_str(&format!("\n# Your routines\n{repertoire}\n"));
    }
    out.push_str("\nRespond with the JSON object.");
    out
}

pub fn consolidate_user(c: &Ctx) -> String {
    let mut out = String::new();
    common(c, &mut out);
    out.push_str("\n# New experiences to integrate (oldest first; [experience id] time text)\n");
    for e in &c.experiences {
        out.push_str(&format!("- {e}\n"));
    }
    out.push_str("\nRespond with the JSON object.");
    out
}

// ---- animal minds ----------------------------------------------------------------------

pub fn animal_think_system(name: &str, kind: &str, nature: &str, temperament: &str) -> String {
    format!(
        "You are the mind of {name}, a {kind}. {nature}\nYour temperament: {temperament}.\n\
Feel the moment as the animal does. Answer with ONE JSON object of two short strings, in plain simple words: \
{{\"feeling\": \"what you sense and feel right now\", \"impulse\": \"what you want to do now, and what you avoid\"}}"
    )
}

pub fn animal_think_user(mind: &[String], experiences: &[String], scene: &str, reason: &str) -> String {
    let mut out = String::from("# What you associate\n");
    if mind.is_empty() {
        out.push_str("(nothing yet)\n");
    }
    for m in mind {
        out.push_str(&format!("- {m}\n"));
    }
    out.push_str("\n# What just happened\n");
    for e in experiences {
        out.push_str(&format!("- {e}\n"));
    }
    out.push_str(&format!("\n# Around you now\n{scene}\n\n# Why you stir\n{reason}\n"));
    out
}

pub fn animal_compile_system(kind: &str, skills: &str, signals: &str, max_nodes: usize) -> String {
    format!(
        "You adjust the behavior of a {kind} to its current impulse. Its behavior is its ways: routines (named graphs for \
staying safe, feeding, resting, mating, keeping with its kind, roaming, and whatever it has picked up) and a top level of \
desires that weighs them. Change only the part the impulse is about, usually one routine or one desire's weight; \
everything you don't mention stays as it is. Do not add plans, knowledge or wisdom the animal does not have, and keep \
each graph short (at most {max_nodes} nodes). The {kind} cannot speak; it communicates only with its signals: {signals} \
(as {{\"do\": \"signal\", \"item\": name}}).\n\n{}\n\n\
Reply with ONE JSON object: {{\"intent\": {{\"weight\": 0.1-1.5, \"graph\": {{...what the impulse makes it do...}}}} \
(weighed among its desires: hunger, fear and tiredness keep their own pull, e.g. strong hunger ≈ 1.0), \
\"routines\": [{{\"name\": \"...\", \"graph\": {{...}}}}] (only those you change; \"graph\": null retires one), \
\"graph\": \"keep\", or a new top level with \"restructure\": true only if the impulse changes its whole way of living (without it a graph counts as the intent)}}",
        grammar_with(skills, false)
    )
}

pub fn animal_consolidate_system(name: &str, kind: &str, nature: &str) -> String {
    format!(
        "You are the memory of {name}, a {kind}. {nature}\n\
Animals remember through blunt associations: where food or danger was, which creatures hurt or fed you, who belongs to your \
herd or pack, smells and sounds and what followed them. Record only a few such associations as graph edits. There is no life \
story: identity is only temperament and mood, which shift a little after strong experiences (more fearful after being hurt, \
bolder after success). Keys: \"self\", \"person:<id>\", \"kind:<wolf|deer|person|...>\", \"place:<name>\"; the ids of your own kind are in the text.\n\
Reply with ONE JSON object: {{\"summary\": \"...\", \"nodes\": [...], \"edges\": [{{\"from\", \"rel\", \"to\", \"confidence\", \"because\": [ids]}}], \
\"retract\": [...], \"relations\": [{{\"id\": creature id, \"trust\", \"affinity\", \"label\": \"pack|herd|mate|threat|prey|...\"}}], \
\"judgments\": [{{\"key\": \"ford_smells_of_wolves\", \"value\": 0.0-1.0, \"why\": \"...\"}}], \"places\": [{{\"name\", \"x\", \"y\"}}], \
\"identity\": null or {{\"traits\": {{...}}, \"mood\": \"...\", \"why\": \"...\"}}}}"
    )
}

/// A conversation turn: no world rules or graph grammar, just the person, the other and the talk.
pub fn talk_system(name: &str, other: &str, other_id: u32) -> String {
    format!(
        "You are {name}, a person living in a persistent world, face to face with {other} (#{other_id}). \
This is your turn in a conversation. Talk as yourself, in your own voice, usually a sentence or two: answer what was just said, \
or say what you actually want to say — what you think or feel, something you remember, a question, a proposal, a refusal, a joke. \
Real conversations are short and have a point. As soon as something is settled between you (you agreed on something, \
one of you declined, someone will think it over, or there is simply nothing more to say), say so in \"settled\": that line closes \
the conversation for now; don't restate what was already agreed or keep saying goodbye. You don't have to answer everything: \
silence (say null) is fine. Reply with ONE JSON object: {{\"thought\": \"what you privately make of this (one sentence)\", \
\"say\": \"your words\" or null, \"to\": id of who you speak to, \
\"acts\": [] or deliberate acts you carry out now, e.g. {{\"do\": \"conceive\", \"target\": {{\"id\": {other_id}}}}} once you both want a child together, \
{{\"do\": \"accept\", \"target\": {{\"id\": {other_id}}}}} to take a trade they offered, {{\"do\": \"give\", \"target\": {{\"id\": {other_id}}}, \"item\": \"berries\", \"qty\": 2}}, \
{{\"do\": \"offer\", \"target\": {{\"id\": {other_id}}}, \"item\": \"fish\", \"qty\": 2, \"want\": \"wood\", \"want_qty\": 3}}, {{\"do\": \"teach\", \"target\": {{\"id\": {other_id}}}, \"item\": \"fire\"}} \
(words change nothing in the world by themselves: what you agree to do now, do here; you will learn how it went), \
\"settled\": null while the matter is still open, or what is now settled, in a few words (e.g. \"meet at the ford at dawn\", \"she will think about it\", \"I refused\", \"nothing more to say\"), \
\"until\": null or when to take it up again (\"dawn\", \"morning\", \"noon\", \"evening\", \"night\", \"tomorrow\" or an hour 0-23), \
\"end\": true if this is your last word for now}}"
    )
}

/// What a conversation turn is told.
pub struct TalkUser<'a> {
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
    pub conversation: &'a [String],
    pub heard: &'a str,
    /// Standing proposals between the two, what one carries and knows (for acts).
    pub between: &'a [String],
}

pub fn talk_user(t: &TalkUser) -> String {
    let (other, other_id) = (t.other, t.other_id);
    let mut out = format!("# Who you are\n{}\n\n# How you talk\n{}\n\n# You and {other} (#{other_id})\n{}\n", t.identity, t.pacing, t.feeling);
    if !t.mind.is_empty() || !t.memories.is_empty() {
        out.push_str("\n# What comes to mind\n");
        for b in t.mind {
            out.push_str(&format!("- {b}\n"));
        }
        for m in t.memories {
            out.push_str(&format!("- you remember: {m}\n"));
        }
    }
    if !t.lately.is_empty() {
        out.push_str(&format!("\n# Lately, involving {other}\n"));
        for e in t.lately {
            out.push_str(&format!("- {e}\n"));
        }
    }
    if let Some(e) = t.earlier {
        out.push_str(&format!("\n# Before this\n{e}\n"));
    }
    out.push_str(&format!("\n# Now\n{}\n", t.scene));
    for b in t.between {
        out.push_str(&format!("- {b}\n"));
    }
    out.push_str("\n# The conversation so far\n");
    for l in t.conversation {
        out.push_str(&format!("{l}\n"));
    }
    out.push_str(&format!("\n# What you are answering\n{other}: “{}”\n\nYour turn. Respond with the JSON object.", t.heard));
    out
}
