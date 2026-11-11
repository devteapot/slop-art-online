# Combat: the starter skills on the live island

Started 2026-11-09. This note records how the living authority runs the game's six starter skills (docs/GAME_BRIEF.md, "Controls" and "Starter skills") for every character, how the game client presents them, the SpacetimeDB documentation the design rests on, what was measured and what was verified. Implementation evidence; the open work is at the end.

**Status.** Implemented and verified on scratch databases (`verify-combat-*`) on the dev-box, SpacetimeDB 2.14.1, seed `island`. No lab or reference world was touched.

## SpacetimeDB documentation consulted (2026-11-09)

Pinned: `spacetimedb = "=2.14.1"`, `spacetimedb-sdk = "=2.14.1"`, server image `clockworklabs/spacetime:v2.14.1`. The live docs' version selector reads 2.0.0, so the claims that decide the design were also checked in the 2.14.1 crate sources (cargo registry).

| Page | What it says | What follows here |
|---|---|---|
| [Event tables](https://spacetimedb.com/docs/tables/event-tables/) | `#[spacetimedb::table(accessor = …, public, event)]`; rows "exist only for the duration of the transaction that created them" (inserts still reach the commitlog); clients get `on_insert` only and cache nothing; "Row-level security applies to event tables with the same semantics as regular tables"; "Event tables cannot currently be accessed within view functions". | Available in 2.14.1 (`spacetimedb-bindings-macro-2.14.1/src/table.rs`: the `event` flag; `spacetimedb-sdk-2.14.1/src/table.rs`: `EventTable`). But the only per-client filter they offer is RLS, and the 2.14.1 source marks it `// TODO: RLS filters are currently unimplemented, and are not enforced` (`spacetimedb-2.14.1/src/lib.rs:108`). A public event table would therefore broadcast every fight to anyone who subscribes to it, which breaks the perception rule. **Not used.** |
| [Views](https://spacetimedb.com/docs/functions/views/) | Per-sender views (`ViewContext`, `ctx.sender()`) "require separate computation for each subscriber"; views read only through indexed lookups (for read-set tracking). | The perceived feed is a **private table read through a per-sender view** (`my_combat`), filtered on an indexed `viewer` column, so each player's view depends only on its own rows. Cooldowns (`my_readiness`) and uses (`my_skill_uses`) the same way. |
| [Tables](https://spacetimedb.com/docs/tables/) | Private by default ("Visible only to reducers and the database owner"); organise by access pattern. | Missiles, uses, timing and the feed are private. What anyone can see of a fighter is a small public row of its own (`fighter`), apart from `vitals` and `activity`. |
| [Table performance](https://spacetimedb.com/docs/tables/performance/) | "organize data by access pattern"; smallest types; "Private tables avoid unnecessary client synchronization overhead"; "Be mindful of unbounded table growth" (cleanup reducers, schedules). | `fighter` is about 50 B and written only when a move starts, releases or ends, or the band changes. The feed expires by an indexed `expires_ms` each tick; uses are kept to the last 24 per character. |
| [Indexes](https://spacetimedb.com/docs/tables/indexes/) | B-trees cost memory and slow writes; equality and ranges. | Indexes only where read: `combat_seen.viewer` (the view), `combat_seen.expires_ms` (expiry), `missile.next_ms` (the sweep), `skill_use.actor` (records). |
| [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) | Group by lifetime; subscribe before unsubscribing; indexed queries are cheaper. | The client subscribes the views and `skill_card` once per connection (so the death screen keeps its rows after the character dies) and joins `fighter` to its moving body window like `character`. |

## Design

### One timing model for every controller

The six starter skills and the older force skills (`attack`, `shoot`, `throw`) share a timing model, enforced by the authority for players and behavior graphs alike:

1. **Intention.** A player's key (`use_skill(skill, target, x, y)`) or a graph leaf (`{"do": "strike", "target": …}`).
2. **Attempt.** `combat::gate` (one windup at a time, a dodge excepted; the recovery after a release; the cooldown) and the skill's Rhai check (requirements, energy, reach, sight).
3. **Accepted.** The windup starts: the cooldown runs from now, the `fighter` row shows the move to anyone looking, `skill_use.accepted_ms` is set.
4. **Released.** Effects apply (a blow, a heal) or a missile leaves; the recovery starts.
5. **Outcome.** What actually happened: hit, blocked, dodged, missed, struck a wall, hit nothing, killed, broken off, refused.

`skill_use` keeps all five for the last 24 uses per character. A player's attempts and refusals are all recorded (the reducer returns `Ok` and the refusal is told back through `my_combat`, so the record survives the transaction). A graph's use is recorded from acceptance; its refusals go back to its leaf (`mind_state.last`) as before, because a graph re-tries at combat cadence and a row per refused retry would grow without bound.

### The skills (numbers are the Rhai script's, `living/scripts/skills.rhai`)

| Key | Skill | Kind | Requires | Reach | Windup | Recovery | Cooldown | Energy | Effect |
|---|---|---|---|---|---|---|---|---|---|
| LMB | `strike` | targeted blow | not young, not yielded, the predator rules (`dares`) | 1.6 + lunge 0.6 | 350 ms | 250 ms | 650 ms | 2 | 10 (15 with a spear) × strength × knack × armor; the full blow lands, like `attack` (a blow that exceeds health kills) |
| RMB | `bowshot` | skillshot missile | a bow and an arrow | 22 m at 30 m/s, radius 0.15 | 300 ms | 250 ms | 900 ms | 1.5 + 1 arrow | 14 × strength × knack × armor on the first body in its path |
| Q | `firebolt` | skillshot missile | `fire_bolt` (needs `fire`) | 16 m at 16 m/s, radius 0.35 | 450 ms | 350 ms | 4 s | 12 | 24 × knack × armor |
| E | `block` | held guard | a person | ±75° in front | raised at once, held up to 8 s | — | 400 ms | 1, then 12 a minute while held | three quarters off a blow from the front; nothing from behind |
| R | `heal` | targeted, self or ally | `mending` (renamed `wound_tending` on 2026-11-10, [world rules](WORLD_RULES.md#mending-is-now-wound_tending)) | 8 m, in sight | 600 ms | 300 ms | 8 s | 15 | +22 × knack, even mid-fight; not on someone fighting you |
| Shift | `dodge` | dash | energy ≥ 5 | 2.6 m at 5.2 m/s | — | 200 ms | 900 ms | 4 | blows and missiles landing during the dash miss; a blow whose target dashed out of reach is dodged too (DODGED to both and to onlookers), where a walk out of reach is only "they moved away" |

- **Targeted skills** resolve against a creature within reach and sight (the body's sight radius and a clear line on the map). A player's targeted move does not walk into reach: out of reach is refused ("out of reach"). A graph's does walk, as every graph leaf always has.
- **Skillshots** are missiles on the authority (`missile`, private). Each tick (16.7 ms, the contract's 60 Hz combat rate) every due missile is swept from its last position along its path: the first body touched (segment against a circle of the missile's radius plus the body's) is struck, a wall, rock or shut gate stops it first (a drop between ground levels or a low thing such as a cart does not: it flies over, as sight passes, [perception](PERCEPTION.md#drops-sight-across-ground-levels)), and its range ends it. Its owner's body is excluded; one that has since died still strikes. A strike runs the skill's `_hit` effects with the struck creature as the target, then the same blow and defense rules as a melee blow (`act::damage`), so armor, guards and dodges work the same.
- **Block** faces where it is aimed (a player's cursor) or, for a graph, toward a windup aimed at the character, else whoever last hurt it, else the body's heading. A blow from outside the arc lands in full and the defender is told its guard faced the wrong way. A player walks with the guard up (no running).
- **Dodge** is movement the rules perform: the existing dash (`motion` with `FLAG_AGILE`) toward the aimed point (a player's movement direction, else away from the cursor) or, for a graph, away from the threat. Its distance and speed are rules (`dodge_dist`, `dodge_speed`); its brief immunity is the dash itself.
- **While rooted** (a strike, shot, bolt or heal winding up, or a dodge dashing) a player's movement input is kept (`readiness.move_*`) and applied when the move ends; a walk under way when the move started resumes the same way.
- **Damage, health and death** go through the existing `vitals` and `act::die`. Death is permanent: rejoining (`join`) makes a new character that inherits nothing; the seed's `newcomer` kit (island: a bow, 30 arrows, 4 berries; `fire`, `fire_bolt`, `mending`) is what every newcomer is given, not anything of a character before.

- **What minds are told of the timing** (since 2026-11-11, branch `mind-skill-timings`, [combat mind](COMBAT_MIND.md) §3.7). A person's mind is told, in its own prompt ("# Who you are", after what it knows how to do), how long the fighting moves **it knows** take: "How long the fighting moves you know take: - strike: winds up 350 ms before it takes effect (others see it coming), then 250 ms to recover; ready again 650 ms after it starts" (`prompts::own_timings`, from `Mind::own_timings`). Which moves: the timed combat skills its body is offered whose techniques it knows (each `<skill>_combat()`'s `knows`, the rule by which a player's bar shows "Unknown"), so one without `fire_bolt` is told bowshot's and strike's timing and not fire bolt's; skills that need only an item (a bow) are known without it. The numbers are the ones `skill_card` shows a player (`Scripts::timing` in `living_rules`, which `combat::cards` now uses too, so there is one source); a dodge is "a dash at once", a guard "raised at once and held up to 8 s", a missile adds its speed. **An opponent's timings are never handed over**: the shared skill reference (the system prompt, the same for everyone) states none, and a move one does not know is for a character to learn by watching. Before, minds were told only "a short windup". Animals are not told (their prompts are built apart; unchanged). Switch: `LIVING_SKILL_TIMINGS=0` (or `off`) on the mind service: no timing lines, the prompts as before.

Changes to existing rules that labs share: `dodge` and `block` now have cooldowns (900 and 400 ms) and energy costs, a person's dodge is 2.6 m at 5.2 m/s (was 2.4 at 9), and a guard covers only the front. Knacks: the new skills use the knack genes of `attack`, `shoot`, `throw` and `tend` (each skill's `knack` in its `<skill>_combat()`), so founders draw exactly the genes they drew before.

### What others see, and what each player perceives

- **`fighter`** (public, joined to the body window): the health band anyone sees at a glance (`living_rules::combat::band`: unhurt, scratched, hurt, badly hurt, barely standing; never exact health), the move under way (`act`, its `skill_card.code`; start, release, end), its target and aim. A character gets a row at its first move or blow; housekeeping refreshes the bands of existing rows once a second; the row goes with death. Like `body`, the window is not a permission boundary; the row holds only what looking at the body shows.
- **`combat_seen`** (private) through **`my_combat`** (per-sender view): one row per human viewer of what that viewer's character perceived: a release, a hit, a miss, a block, a dodge, a heal, a missile's launch and impact, a death, a refusal (actor only), and, for the one who died, who saw it. Recipients are the actor and target (always, with the amount) and the human players whose characters are within their own sight of where it happened (without the amount). Minds still perceive fights through `experience`, unchanged. Rows expire after 4 s (a death and its witnesses after 2 minutes). **Since 2026-11-10** ([frames](PERCEPTION.md#frames-what-others-do-reaches-a-player-once-per-frame)): the two involved get their rows at once and keep them 4 s, as before (1.5 s from 2026-11-10 until `fix-dodge-events`, which lost verify-player's dodge events on a busy host); an onlooker gets its rows at its next frame and keeps them 300 ms, except a death, which reaches it at once; only the one who died keeps its death and its witnesses, until it joins again (a join clears the player's feed). Others' `fighter` rows reach a player through `seen_fighters` at its frame.
- **`skill_card`** (public, one row per combat skill: 13 with the shipped script): each combat skill's bar slot, cost, windup, recovery, cooldown, reach, presentation code, aim, missile radius, guard arc and the bar's needs hints, rewritten whenever a skill script is installed, so the client shows the bar and names the codes in `fighter` and `combat_seen` without running the rules (see "Where combat rules live").

### Data paths, readers and growth

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| A player presses a skill (`use_skill`) | character by controller, body, readiness, steer, activity | `skill_use` (1), maybe `combat_seen` (refusal), activity, readiness | `character.controller`, PKs | the player (view) | at most the input bucket (`input_hz` 30/s, shared with movement) | bounded: 24 uses per character |
| A windup starts (any controller) | readiness | readiness, `fighter`, `skill_use` | PKs | `fighter` subscribers in the window | per move | none |
| A release | target, body | vitals, `fighter`, `skill_use`, `combat_seen` × viewers | PKs, chunk cache | viewers in sight | per move | expires in 4 s |
| A missile in flight | due missiles, the chunk-body cache along the step, the cached map | the missile row | `missile.next_ms` | — | every tick while it flies (≤ 1 s) | deleted on impact |
| Feed expiry | the viewer's own rows by expiry (module memory), then a sweep of rows a second overdue | deletes | PK; `combat_seen.expires_ms` for the sweep | the viewer (view delete) | at the viewer's frame; the sweep at 1 Hz (since 2026-11-10; it was every tick) | — |
| Band refresh | every `fighter` row, its vitals | changed bands only | PKs | window subscribers | 1 Hz | one row per character that has fought, deleted at death |
| Human viewers | a module cache of the living human-controlled characters (one scan of `character` per module instance, after a join or a death) | — | — | — | per event: the chunk-body cache within sight, filtered by the cache | none |

No new whole-World scan was added to a routine action. The band refresh scans `fighter` (one row per character that has ever fought, alive) once a second.

**Since 2026-11-09 (second perception change):** a viewer in sight is one within its own sight (day, night, a torch) with a clear sight line to where it happened (`perception::in_sight`: walls, rock and shut gates hide), for the feed and for minds' fight percepts alike; the band others see is each viewer's projection (`seen_fighters` carries the band from `projected`, and a band change reaches those rows through `perception::health_moved`). See [perception](PERCEPTION.md#minds-see-what-their-character-sees).

### Hostile wildlife and residents

- **A hostile pack by seed.** `packs` in the seed places animals on purpose: island seed, 4 wolves near a deer herd 370–800 m from the newcomers' arrival point and 40 m clear of roads (40–75 m from the arrival until addfe04, then 370–520 m from it until 2026-11-10; see [island authority](ISLAND_AUTHORITY.md#wildlife-placement-2026-11-10)), `bold` (their background says so; the rules' `dares` lets a bold animal attack a healthy adult) on the `wolf_bold` instinct graph in `instincts.json` (attack a person within 10 tiles, fight back, flee when badly hurt, return to their den beyond 25 tiles, hunt deer when hungry). The species, the other island wolves and the lab seeds are unchanged; a bold wolf's pups are not bold.
- **Residents defend themselves** on their existing graphs: the shared `stay safe` routine attacks whoever hurt them and gangs up on a wolf with two or more people near. No model is called (`rules.minds = false`).
- **Graph fighters** can use the starter skills like anyone; `spawn_skirmish(n, spacing)` (admin, for benchmarks and scenes) sets up two communities whose people strike in reach, shoot at range, block or dodge when threatened and heal when hurt. A new relation filter, `outsider` (not of my community), lets a graph pick the other side.

### The client (`living/game`)

- `combat.rs`: input (LMB strike, RMB bow shot, Q fire bolt, E block held, R heal, Shift dodge; Shift held still runs), aiming at the cursor's ground point, the target under or nearest the cursor (within 3.5 m of it), the clip each drawn character plays, and the aim and range indicators, drawn only while a skill key is held. RMB was click-to-move; it is now the bow shot, as the brief decided. Since 2026-11-11 a left tap on a person who is not hostile to you opens the text box to them instead of striking; a held press strikes anyone ([game brief](GAME_BRIEF.md#talking-and-tapping-2026-11-11)).
- **Prediction, only where latency demands it.** On a press my character's clip starts at once; it ends when the authority's `fighter` row confirms the move (the authority's timing then drives it), when `REFUSED` arrives, or after 600 ms. Movement is never predicted: the dodge's dash is the authority's body motion, about one round trip after the press. Cooldown sweeps come from `my_readiness`.
- `vfx.rs`: slash arcs on releases (red for an animal's bite), arrows and fire bolts flying along the authority's launch until its impact, the bolt's trail and burst, hit sparks, a block flash, a dodge ring, a heal glow, a raised guard's arc and a fire bolt's windup ember. All share six meshes and nine unlit additive materials made once; effects fade by shrinking.
- `live.rs`: one-shot clips over locomotion (`sword_slash` / `sword_overhead` / `sword_thrust`, `bow_shoot`, `cast`, `block` held at its guard pose, `dodge` on the rules' dash track, `hit`, `death` held; one-shots are timed on the display clock, and a dash's clip is not predicted), a body facing its move's aim, and corpses: someone I saw die stays where they fell for 7 s playing `death` after the authority removes the body. Animals are the procedural creatures and have no clips.
- HUD (`ui/live.rs`, `ui/numbers.rs`): the skill bar from live cooldowns, `skill_card` costs, my inventory and know-how (no bow, no arrows, unknown, too tired); the target frame and nameplates with the perceived band; hostile stance for whoever's move is aimed at me; floating numbers for blows I dealt or took and heals; the death screen's cause and the witnesses my character's death was seen by.

### Backstabs when sight depends on facing

Since 2026-11-11 (`fov-1`, [perception](PERCEPTION.md#the-field-of-view-seventh-change)). With the world's `fov_on` law on, a blow from behind can land unseen. This is part of the switch, accepted with it. A guard already covers only the front (±75°). What changes is whether the one struck sees the windup coming.

- **The rule.** A graph's `{"threatened": true}` holds, while the field is on, only when the one winding up is seen by the sight rule (`living_rules::sight::sees`). A player sees a windup only through its perceived set: the attacker's `fighter` row reaches it in `seen_fighters` only when the attacker is in its scene. With the field off, `threatened` is as before: any hostile windup aimed at me, seen or not.
- **When a blow from behind lands unseen, with the shipped values** (near ring `fov_near_m` 3 m, `fov_near_dark_m` 2 m in the dark; side vision out to 110° at a third of sight; full sight within 70°). The one winding up is unseen when it is more than 110° off the target's facing and outside the near ring. With sight 11 m by day it is also unseen between 70° and 110° when farther than a third of sight (3.7 m by day; 2 m at night, where the near ring decides). A player already perceiving the attacker keeps it 10° and 1 m longer.
  - **A strike** reaches 1.6 m plus a lunge of 0.6 m. By day a striker behind is therefore always within the 3 m ring: it is seen, and a graph guards and turns to it as before. In the dark the ring is 2 m, so only a strike from 2.0 to 2.2 m behind, at the edge of its lunge, is unseen.
  - **Missiles** (`bowshot` 22 m, `firebolt` 16 m) from behind are unseen beyond the ring, and land unless the target turns.
  - **A charge or a dash** from behind is unseen while it is outside the ring. A graph-driven striker walks into reach before its windup, and a player's strike starts within reach, so by day the windup itself starts inside the ring.
- **A player's look turns the guard.** `block` is aimed `facing`, so a raised guard covers the front of the body as `human_face` turns it ([perception](PERCEPTION.md#the-players-look-human_face)).
- **The near ring is a law.** The owner can lower it with `set_world_law` (`fov_near_m`, `fov_near_dark_m`). Verified with both at 0.5 m (`verify-core` `scenes.py fov`): a strike from 1 m behind gets no guard from the one struck, and the blow lands.

## Where combat rules live

Decided 2026-11-09, after the first pass: the authority's Rust had chosen which skill is which by matching names (hostile-skill lists, `TIMED`/`AIMED`/`ROOTED`, `"bowshot" | "firebolt"`, `== "dodge"`, `== "block"`, `"attack" | "strike"`, a guard's `* 0.25`, `HOLD_MS`), so a new combat skill needed Rust edits in a dozen places.

**The rule.** A combat skill is whatever `living/scripts/skills.rhai` says it is. Each one declares its shape in `<skill>_combat()`, a map of traits (the list and their meanings are in the script, above the shapes): `aim` (`creature`, `self_or_ally`, `point`, `facing`, `dash`, `none`), and the flags `timed`, `rooted`, `hostile`, `reflex`, `real_time`, `melee`, `closes_in`, `menace`, `force` and `dares`, the guard numbers `hold_ms`, `arc` and `takes`, the `knack` gene it uses, and the bar's hints `needs` and `knows`. Whether it fires a missile follows from `<skill>_missile` existing; a `point` skill without one is refused when the script is installed, as is an unknown trait. `skill_bar()` lists the bar in order. `use_skill` accepts only skills on the bar.

**The engine keeps generic primitives** and picks one by trait, never by name: a dash (`aim: "dash"`: the motion, its immunity, `<skill>_dist` and `<skill>_speed`), a held guard (`facing`: faces the aim, takes `takes` of a covered blow within `arc`, held up to `hold_ms`), a missile (`point` + `<skill>_missile`), a melee blow (`melee`: the miss out of `reach + lunge(kind)`), a menace (`menace`), and the combat timing (`timed`). The older force skills (`attack`, `shoot`, `throw`, `threaten`, `yield`) and `seize`/`tend` declare shapes too, so there is one classification. The rules test `combat_shapes_classify_the_existing_skills_as_before` asserts that the shapes reproduce every name list they replaced.

**Read once.** `Scripts::new` reads every `<skill>_combat()` and `skill_bar()` when the script compiles and keeps the result (`living_rules::combat::Shapes`) in the `Scripts` value the authority already caches per script revision. Lookups are a map lookup by name; no Rhai call was added to the tick or to a skill's use. The mind service reads the same shapes from the world's `script` row (`prompts::set_rules`) to tell real-time moves from acts.

**Presentation codes.** `fighter.act` and `combat_seen.skill` stay `u8` (a fighter row is written at every move; a string would grow every update for every subscriber). Codes are stable (since 2026-11-09, at the user's request; they first followed name order, which renumbered skills when one was added). The authority keeps a private `skill_code` table (`living/authority/src/codes.rs`) with one code space for combat skills (`skill_card.code`, `fighter.act`, `combat_seen.skill`) and one for shown skills (`act_card.code`, `doing.code`). At each `install_script` a skill that has a code keeps it, a new skill takes the next code never given in its space, and a removed skill's code stays reserved, so a row written under one script never names another skill under the next. A world that predates the table takes over the codes its cards already carry at its next install. The cached `Scripts` gets the registered codes when it is compiled (`codes::apply`); outside the authority (the mind service, rules tests), codes default to name order and nothing reads them. The client maps code → skill through `skill_card` and `act_card`, which it already subscribes, so a new skill still reaches it with no Rust edit on either side. A space holds 255 codes over the world's lifetime; an install that would need a 256th is refused. `skill_use` records skill names, so the evidence never depends on codes.

Proof (`verify-codes-1`, `.local/living/verify/codes-1/codes_proof.txt`): installing a script that adds a combat skill and a shown skill sorting first left every existing code unchanged (strike stayed 9; a bow shot's `combat_seen` row still carried bowshot's 3, where name order would give 4); removing them and adding others gave fresh codes (14 → 15, 18 → 19) without reuse; reinstalling the shipped script left every code as it began.

**The client** (`living/game`) reads its bar (slot by key: LMB, RMB, Q, E, R, Shift), targeting (by `aim`), reach, missile radius and guard arc from `skill_card`. How a skill looks (clip, effect, icon) is the client's own presentation: by name for the skills it was drawn for, otherwise from the card (`point` with radius ≥ 0.25 is a bolt, else an arrow; `facing` a guard; `dash` a roll; `creature` a slash). A skill the client has never seen plays that fallback.

**Columns added to a live table.** `skill_card` gained `code`, `aim`, `radius`, `arc`, `needs` and `knows`, appended last with `#[default(..)]` so `just living-publish` migrates an existing world without `--delete-data` ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations), [default values](https://spacetimedb.com/docs/tables/default-values), docs version 2.0.0, checked against the 2.14.1 macro: a default must be constant, so `needs` and `knows` are comma-separated strings, not lists). The new values appear at the next `install_script`, which `living-publish` runs.

**What a new combat skill needs.** Its functions in `skills.rhai` (`_combat`, `_check`, `_duration`, `_done`, and `_missile`/`_hit` for a skillshot), its timing in `combat_cooldown`/`combat_recover`/`combat_cost`, a place in `skill_bar()` if players use it, and its `<skill>_spec()` (target, reach and a description for minds) in the same script, which graph normalization, approach, the minds' prompts and the client's verbs read. Since `rules-2` (2026-11-10) there is no Rust catalog line: an install refuses a skill with rules but no spec ([world rules](WORLD_RULES.md#skills-declare-their-spec-in-the-script)).

**Still named in Rust, deliberately:**
- `act.rs` `report`'s list of notable successes (`attack`, `threaten`, `yield` among `build`, `give`...): which outcomes become a mind's experience, not a combat classification.
- Chronicle and percept kinds (`"attack"`, `"yield"`): event vocabulary, not skills.
- `spawn_skirmish`'s graphs (`lib.rs`): content for the benchmark scene.
- The walking and resting skills that are real-time (`combat::MOVES`: wander, flee, follow, wait, sleep, rest, graze) and `flee` as a reflex: engine motions, not combat skills.
- The client's look table by name (presentation, with the fallback above) and one plural, "No arrows".
- The lab observer (`living/viewer`) still reads activity skill names; it is the developer client the game will replace.

One behavior moved with it (superseded the same day by "One damage rule" below, which removed the mode): graph normalization now keeps a hurt/kill mode word on any skill that takes no item (it was kept only for `attack` and `strike`, because normalization has no script). The authority gives the mode meaning only for a `melee` skill and drops it from any other at `begin`, so what a character does is unchanged; a graph's stored and described form now shows a mode a model wrote on, say, a bow shot.

## One damage rule (2026-11-09)

The user decided on 2026-11-09: "A blow does its damage; if the damage is more than the HP, they die. No way to limit the strength of an attack for now. If someone wants to intimidate other people, they would just use a non-lethal attack."

**Before.** A blow between people defaulted to a "hurt" mode (`attack_mode` in the script): `attack_check` refused once the target was below `hurt_enough` (40%) of full health or had yielded, and `attack_done` and `strike_done` held a blow short of `hurt_floor` (10%), unless the graph's item said "kill". So a player's LMB beat a resident but could not kill one. Bow shots and fire bolts ignored the mode (the authority always passed "kill" for missiles). A yield held back blows meant only to hurt, and the seed's `rules.yield_shield` could hand that to the minds' norms instead.

**Now.** One rule for every blow, missile and effect, for players and graphs alike: it deals its damage (`act::damage`, after guards and dodges), and a creature at 0 health dies through `act::die`. Removed:
- `skills.rhai`: `attack_mode`, `hurt_enough`, `hurt_floor`, `looks`, the hurt checks in `attack_check` (the yield shield and "you have hurt X enough") and the caps in `attack_done` and `strike_done`; `skill_io` for `attack` and `yield`; the `melee` trait's description.
- `living/rules`: `SkillCtx.yield_shield` (and its Rhai field), `Scripts::text` (its only caller was `attack_mode`), the catalog help for `attack`, the `Shape::melee` description. `normalize::attack_mode` became `force_word`: a mode word (`item`, `mode` or `intent`: "hurt", "kill", "beat", "to kill"…) on a skill that takes no item is dropped and a warning says so ("a blow does its full damage and kills at 0 health (there is no hurt or kill mode); to frighten without harm, threaten"). Warnings go where every other normalization slip goes (a deliberation's thought `detail.pruned`).
- `living/authority`: `act::attack_mode`; the mode argument of `act::damage` (and the missile's "kill"); the "to hurt"/"to kill" label; the note after a beating that had done enough; the `YIELD_SHIELD` build flag (`build.rs`) and the `yield_shield` entries of `aske-coast-dynamic.json` and `aske-coast-yieldnorm.json` (now meaningless); `"assault"` among the town's commotion kinds. `act::begin` still drops a force word left on a blow by a graph stored before this change.
- `living/mind`: the FORCE paragraph and the yield line of the world rules.
- `spawn_battle` and `spawn_skirmish`: the `"item": "kill"` on their attacks and strikes.

**What the story says.** A first blow on a person, or by a person, is chronicled `attack`, "Siv attacked Grim" (it was `assault` "beat" or `attack` "tried to kill"); the victim feels "Siv attacked you (n damage)" and a mind is woken with "Siv is attacking you!". The first blow after a yield is "Siv struck Grim, though Grim had yielded" (witnessed at 0.95), and a death that follows is "killed by Siv, after yielding", as before.

**Yield.** What it still does: for `yield_ms` (20 s) the yielder's own attacks, strikes, shots and throws are refused, and striking someone who has yielded is news to everyone in sight. Blows on the yielded land in full.

**Intimidation** is `threaten` (`menace`), which does no harm. No new skill was added.

**Now lethal where it was not.** No seed or instinct graph carried a mode word, so every person-against-person attack in them ran in hurt mode by default; all of these can now kill:
- **Residents defending themselves.** The island's and the repertoire's `stay safe` routine answers a blow with `attack` on the attacker while not losing. A player who strikes a resident is struck back with full blows, and a resident can now kill the player (before, its blows stopped once the player was below 40%). The same routine yields once the resident is below 40% (no wolf near) and flees if struck again; a player who keeps striking a yielded resident can now kill them.
- **A player's strike** can kill a resident (`verify-player` `combat.py` scene `kill`).
- **Any fight between people on graphs** (labs, minds that write `attack` on a person, `spawn_battle`, the skirmish) goes on to a death unless someone breaks it off, flees or yields and is spared by the striker's own graph.
- Unchanged: the person instinct (`instincts.json`) only flees and yields; animals always fought to kill; bow shots and fire bolts always did full damage.

**SpacetimeDB.** No table, column, reducer, view or subscription changed, so a running world updates in place with no migration. The SpacetimeDB documentation was not consulted again for this change, because no SpacetimeDB feature is designed or changed; the pages consulted for combat are in the table at the top. The rows a blow writes are the same (`vitals`, `fighter`, `combat_seen`, `chronicle`, `experience`); a beating blow no longer re-runs the skill's check after landing.

## Measurements

All on the dev-box: 32-thread AMD x86_64, Fedora, rootless podman, SpacetimeDB 2.14.1 in my own scratch container (`slop-combat-stdb`, own volume), seed `island` (seed 7, 2048 m), `rules.minds = false`. No mind service, no observer. Other agents' builds kept the load average at 4.8–7.6, so single maxima are indicative.

### Server tick with combat active

`living/tools/bench.py` (60 s windows, the module's tick spans), database `verify-combat-bench`, fresh. No subscribers during the windows. The world's own 197 residents and 34 animals live on their graphs throughout. A skirmish is `spawn_skirmish(n, 12)`: two communities of n/2 people with bows (40 arrows), `mending`, and the starter-skill graph, about 30 m north of the arrival point. Each window starts about 4 s after the spawn and covers the fight from first contact; most fighters were dead by its end.

| Window | Alive at end | Ticks/s | Evaluations/s | Hits / blocked / dodged | p50 | p95 | p99 | Max | Over 16.7 ms |
|---|---|---|---|---|---|---|---|---|---|
| At rest | 197 people, 34 animals | 60.3 | 306 | 0 / 0 / 0 | 1.11 | 1.85 | 2.30 | 3.69 | 0 of 3,615 |
| Skirmish of 20 | 202 people (20 fighters added; some died) | 60.3 | 378 | 103 / 40 / 4 | 1.30 | 2.25 | 2.91 | 3.85 | 0 of 3,615 |
| Skirmish of 200 | 205 people (200 added; 217 dead in the world by the end) | 59.2 | 912 | 1,158 / 284 / 60 | 1.95 | 8.95 | 16.19 | 25.35 | 32 of 3,568 |

Tick times in ms. In the 200 skirmish the time went to combat cadence (`tick.combat`: p99 8.3 ms, 62.6 ms of work per second), wakes (34.6 ms/s), activity timers (26.0 ms/s) and missiles (`tick.missiles`: p99 3.8 ms, 15.3 ms/s), against 31 ms/s for the 1 Hz evaluations of everyone. The 20 slow ticks the bench lists are all in the first second of the window, the moment the lines met; it lists only the first 20 of 32. In that battle 1,566 arrows struck someone, 102 were dodged, 206 strikes were blocked, 208 heals landed, and 157 bow shots failed at the release (their target had moved or died).

A first run had all graph fighters blind to the new skills' windups (`{"threatened": true}` counted only the older attacks), so nobody blocked or dodged: p50 1.37, p95 8.0, p99 11.7, max 19.3, 4 slow ticks. Defense makes the 200 battle about 40% more expensive at p99, mostly in combat cadence.

This is a 200-character melee and archery battle beside 231 other characters for one minute, without subscribers, minds or players. It is not the contract's 2,000 characters with a 200-character local battle for 8 hours, and it is at the edge of the 16.7 ms budget at p99.

### The game client during combat

`living-game` release, headless 1600×900, Vulkan on the Radeon 8060S, uncapped (`LIVING_GAME_FPS_CAP=0`), `island perf` 2 s means. One client ("Watcher") at the arrival point; a skirmish of 100 spawned 30 m north of it, at night in rain. Bytes are the server's `spacetime_num_bytes_sent_to_clients_total` for the database (`living/tools/client_bytes.py`), and only this client was connected.

| | Frame time (2 s means) | Bytes sent to the client |
|---|---|---|
| Calm, 30 s, 39 characters in the window | 7.0–7.8 ms (worst frames 9–20 ms) | 5.7 kB/s (172 kB of updates) |
| Skirmish of 100, its first 60 s | 15.4 ms at contact (4,630 meshes), 11–14 ms as fighters fell, about 9.5 ms once most were dead; worst frames 18–28 ms | 23.2 kB/s (1.39 MB of updates) |
| The spawn's frame | 250 ms (100 new characters' models loading) | — |
| At join | — | 38.8 kB of subscriptions |

The watcher was beyond its night sight (6 tiles) of the fight, so `my_combat` sent it nothing and it drew no effects or numbers: its battle bytes are the body, character and `fighter` rows of the window. Effects for a fight in sight were exercised in the photographs below but not timed.

## Verification

Free tiers only, scratch `verify-*` databases on my own container, no model calls. Evidence was produced under `.local/living/verify/` in the dev-box worktree and copied to the Mac checkout's git-ignored `.local/living/verify/combat-evidence/` (tokens and harness state left out); the photographs are listed below.

Code under test: `e0c9d1f` plus this change on the dev-box. The change was then applied to the Mac checkout (now at `ef36d44`); the commits since `e0c9d1f` touch no file of this change except `living/game/src/main.rs`, where its three lines were re-applied by hand.

| Surface | What was driven | Result | Evidence (`.local/living/verify/combat-evidence/`) |
|---|---|---|---|
| Rules | `cargo test -p living-rules` (inside `cargo_checks.py`) | 82 passed, including the combat geometry (sweeps, guard arcs, bands, codes) and `starter_combat_skills_follow_the_rules` | `core-combat-20261109-054716/` |
| Core | `cargo_checks.py` (rules 82, authority 10, mind 47, viewer sync 3); scenes `tick`, `needs`, `seize`; `verify_steering.py`; `verify_mechanics.py`; the new `skirmish` scene on an island world | all pass except mechanics: 21 of 23 on the first world, failing "a net brings in two fish at once" and the chained "smoking, bow, arrows and leather" (the walker crafted the net and never gathered fish). See the reruns below. `skirmish`: 8 of 8 | `core-combat-20261109-054716*`, `core-combat-mech-*` |
| Player | `verify-player/scripts/combat.py` on an island world with the player identity: refusals, strike, bow, bolt, block front and back, dodge, heal, the bold pack, death, witnesses, rejoin | 23 of 23 | `player-combat-20261109-054716/combat.json`, `actions.log` |
| Client | `verify-client/scripts/run.py`: base subscriptions, privacy, views, the reducer matrix (180 calls, now with `use_skill`, `release_skill`, `place_at`, `spawn_skirmish`), the new combat checks, reconnect | 16 PASS and the 2 known XFAILs (anonymous `experience` and `thought`). The first run failed "combat feed scoped to its viewer": the probe ran a minute after the refusals and the 4 s feed had expired; the driver now refuses a strike right before the probe | `client-combat-20261109-060621/` (passing), `client-combat-20261109-054716/` (the first) |
| Game client | headless `living-game` scripts (`LIVING_GAME_LIVE`) on `verify-combat-1` and `verify-combat-bench`, with `living/tools/combat_scene.py` setting scenes (admin `place_at`, `set_behavior`) | photographs below; the client's own input path (`skill:` steps go through `use_skill`) | `logs/client-{a,b,c}.log`, `logs/scene-*.log` |
| Bindings | `just living_compose=~/combat-shim/compose living-generate` | 15 new generated files; regenerating again changed nothing | `living/bindings/src/generated/` |
| Project check | `just living-check` in the Mac checkout at `ef36d44` with this change | exit 0; rules 82 passed; the only warnings are the macOS linker's `__eh_frame` note. A run in between failed to compile the game against stale bindings: another checkout had built into the shared `living/target`, and cargo took those newer artifacts as fresh; touching this change's sources fixed it | |

**Mechanics reruns.** The net check failed in 3 of 3 fresh worlds with this change and passed in 2 of 2 on the base commit (`e0c9d1f`, same container; 23 and 22 of 23, the 22 failing the documented forest-clearing flake). An instrumented run showed the cause: the walker's nearest fishing spot had been fished out ("the fishing_spot is depleted"), so the gather failed and the chained smoking and crafting check failed with it; in isolation the net brought in 2 fish. The driver (`living/tools/verify_mechanics.py`) now picks the nearest spot holding at least two fish. After that: 21, 21 and 23 of 23. One run failed the net again with no reason in the walker's last experiences (its gather leaf targets the nearest spot it sees, which can still be an emptied one), and one failed the documented conception and expecting-parent pair. Why residents empty that spot more often with this change is not established.

**Photographs** (Mac checkout, git-ignored `.local/living/verify/combat-photos/`; 1600×900, headless, dev-box):
- each skill: `aim-bowshot.png`, `bowshot.png`, `aim-firebolt.png`, `firebolt-flight.png`, `firebolt-impact.png`, `aim-strike.png`, `strike.png`, `block.png`, `block2.png`, `dodge.png`, `hit.png`, `heal.png`, `heal2.png`, `hud.png`;
- a skirmish with the bold wolves: `wolves-1.png`, `wolves-bow.png`, `wolves-bolt.png`, `wolves-strike.png`, `wolves-block.png`, `wolves-heal.png`, `wolves-dodge.png`, `wolves-late.png`;
- the death screen and rejoining: `death.png` ("Killed by Frost the wolf", seen by two wolves), `rejoined.png`;
- a 100-fighter skirmish seen from 30 m at night: `watch-calm.png`, `watch-battle-1.png` to `-3.png`.

Not covered: real input devices (mouse and keys were scripted through the same input path), effects timed under load, a person-vs-person kill by a player, the minds' reading of the new skills (no mind service ran), and how fights look in daylight in the town square.

### The trait change ("Where combat rules live"), 2026-11-09

On the Mac checkout (Apple Silicon, Docker Desktop, SpacetimeDB 2.14.1 in the shared `sao-living_spacetimedb_1`, load average 3–5 from other work throughout), scratch `verify-*` databases only, no model calls. Evidence under the git-ignored `.local/living/verify/`.

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Project check | `set -o pipefail; just living-check` | exit 0; rules 84 passed (adds `combat_shapes_classify_the_existing_skills_as_before` and `a_new_skill_needs_only_the_script`) | — |
| Core | `cargo_checks.py` (rules 84, authority 10, mind 47, viewer sync 3); scenes `tick`, `needs`, `seize` (all pass, the yielded seizure included); `skirmish` 8 of 8; mechanics | mechanics: the first run crashed in the driver edit below (`place_at` given strings); after the fix 23 of 23 in two fresh worlds | `core-traits-1*/`, `core-traits-mech-1/`, `-2/` |
| Player | `combat.py --fresh` on island worlds | 22 of 23 (the dodge scene's driver still waited for the old fixed code 1; fixed to read `skill_card.code`), then 19 of 23 (block front and back, dodge, heal: the resident attacker never struck; not reproduced, cause not established), then 23 of 23 | `player-traits-1/`, `-2/`, `-3/` |
| Client | `verify-client/scripts/run.py` | 16 PASS and the 2 known XFAILs; `skill_card` has 13 rows | `client-traits-1/` |
| Throwaway skills | `icebolt` (point, missile) and `shove` (creature, melee) added only to an installed copy of the script and the bar, plus two `SkillSpec` lines built into a private module (removed after): player windups show their codes, the bolt flies and strikes, the shove hurts and is refused out of reach; a graph leaf of each is recorded from acceptance and lands; a graph shove with `"item": "kill"` keeps its mode ("shove to kill") and kills through the death rule | 16 of 16 | `throwaway-traits-1/throwaway.json`, `throwaway.py` |

**Skirmish of 200, tick time** (`bench.py`, 60 s from about 4 s after `spawn_skirmish(200, 12)`, island, no subscribers), base commit `25b7b7b` against this change on the same Mac:

| | p50 | p95 | p99 | max | over 16.7 ms | `tick.combat` ms/s |
|---|---|---|---|---|---|---|
| base, run 2 | 3.17 | 8.48 | 11.50 | 41.4 | 4 of 3,594 | 56.3 |
| base, run 3 | 3.36 | 8.65 | 11.00 | 16.0 | 0 of 3,594 | 61.1 |
| change, run 1 | 3.43 | 8.50 | 11.42 | 24.8 | 3 of 3,594 | 57.6 |
| change, run 2 | 3.50 | 8.41 | 11.58 | 18.3 | 3 of 3,598 | 62.0 |

p95 and p99 are the same within run-to-run spread; p50 is 0.1–0.3 ms higher in both change runs, about the size of the spread between the two base runs, so a small per-move cost from the trait lookups is possible but not established. (Base run 1 was lost to a `bench.py` bug, a log line stamped on the exact second; fixed.) These Mac numbers are not comparable to the dev-box table above (1.95 / 16.19 ms). This is still a one-minute 200-fighter battle, not the contract's workload.

### The one damage rule, 2026-11-09

On the Mac checkout (Apple Silicon, Docker Desktop, SpacetimeDB 2.14.1 in the shared `sao-living_spacetimedb_1`), code `b7cf7fb` plus this change, scratch `verify-*` databases only, no model calls. Evidence under the git-ignored `.local/living/verify/`.

| Surface | What was driven | Result | Evidence |
|---|---|---|---|
| Project check | `set -o pipefail; just living-check` | exit 0; rules 87 passed (the graded-force test became `a_blow_does_its_damage_and_a_yield_holds_back_only_the_yielder`, the normalization test `force_words_on_a_blow_are_dropped_and_said`) | — |
| Core | `cargo_checks.py` (rules 87, authority 10, mind 47, viewer sync 3); `tick`, `needs`, `seize` | all pass; seize's last check: a blow kills someone who yielded and is news ("Walker1 struck Walker2, though Walker2 had yielded"; "killed by Walker1, after yielding") | `core-fm-base/` |
| Core | mechanics | 22 of 23, then 23 and 23 of 23 after a driver fix (the new yield check read health after the post-yield blow had landed; it now reads the damage the victim was told) | `core-fm-mechanics/`, `-2/`, `-3/` |
| Core | `skirmish` (island), `town.py` (island), `codes.py` | 8 of 8, 21 of 21, 10 of 10 | `core-fm-skirmish/`, `core-fm-town/`, `core-fm-codes/` |
| Player | `combat.py --fresh` (island), with the new `kill` scene | 25 of 25 twice: strikes kept landing below 40% and 10%, and the strike that exceeded health killed (4.5 health, 12.3 strike: "killed Nogar (12)", cause "killed by Tester", chronicle `killing`) | `player-fm-combat/`, `player-fm-kill2/` |
| Client | `verify-client/scripts/run.py` | 17 PASS and the 2 known XFAILs (anonymous `experience` and `thought`) | `client-fm-20261109-121103/` |

Not covered: a mind deliberating under the new prompts (no mind service ran), a resident's `stay safe` routine killing a player who attacked it (the routine was not driven against a player), and the game client.

## What is missing

- **More skills, and learning them.** Six skills on a fixed bar; no skill choice, no skill-learning path beyond the seed's newcomer kit and know-how. Classes from combinations are not yet possible beyond what the six allow.
- **Balance.** Numbers are a first pass, untuned against players. Since "One damage rule" every blow does its full damage, so fights between people end in deaths unless someone breaks off; there is no way to limit a blow's strength yet.
- **Battles at the contract's scale** are measured only as far as reported below; 2,000 characters with a 200-character local battle for 8 hours is not.
- **Perception.** The feed is perception-scoped; the public `body`, `fighter`, `vitals` and `activity` tables are not (the existing gap, game brief core work 1).
- **Prediction.** No client-side movement prediction; the dodge and every move are a round trip behind the press. Input-to-outcome latency (contract: ≤ 150 ms p95 at 80 ms RTT) is unmeasured.
- **Animals** have no clips (procedural creatures), so a wolf's bite shows only as a red arc.
- **Body size** is still not a rule; giants and small folk fight as adults.
- **Known simplification: missiles ignore height.** A missile follows the sight rule (`Map::passable_missile`): it flies over a drop between ground levels and over anything low or open at eye height (`Terrain::Drop`, `Terrain::Low`: a cart, an open stall, a well; [perception](PERCEPTION.md#drops-sight-across-ground-levels)), and stops at a wall, rock or a shut gate. The authority is 2D: it keeps no ground heights after hosting (docs/ISLAND_AUTHORITY.md), so it cannot tell a shot down a terrace from one up a retaining wall, or a bolt that clears a counter from one that would hit it. Both fly. Making uphill shots harder, or low things catch some missiles, would need heights in the rules: the levels as layers of docs/FLOORS.md "Verticality", not a terrain class.
