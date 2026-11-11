# Interface from rules and skills

Status: Approved 2026-11-11 as the design; steps are built in order; open questions below are not yet settled. Step 1 is built on `ui-decl-1` (in review by the Spark, not yet merged); nothing else is built. Line references are to `origin/main` at `bade5c09` unless a branch is named.

The owner's idea: "Most of the UI is related to the world rules or skills. So I think we should have a way to compose the UI by those rules and skills, with a kind of framework that attaches to exposed primitives from the game engine that can be scripted by the rules and skills, in addition to the behaviour. They should also describe how the user interacts with these systems and how they plug into the world."

**The design in one paragraph.** Each skill and way of speaking in the rules script can declare its interface as data, in a `<name>_ui()` map beside its `_spec()` (or `_speech()`) and `about`:
- where it attaches: the bar, a person, a thing, the ground, an item, oneself or the text box;
- which input it takes: tap, hold, toggle, aim at a point, aim a direction, pick a person, pick an item, drag onto, or words;
- what the player must choose;
- what shows while it runs and when it is refused;
- which named icon, clip family and effect it uses.

`living_rules::script` reads these maps once, at compile time, into a typed `UiSpec`:
- The authority's install refuses a bad map, as it refuses a bad law.
- The client reads the same `UiSpec` from the script it already compiles.
- The mind reads the same script for its options.

Anything that changes what a character may do is a rule, not a declaration. For example, "a strike needs the weapon drawn" belongs in the combat shape, where the authority enforces it for players and minds alike. `_ui()` only says how the client presents it.

The client owns a small fixed set of primitives (section 2: bar, slot, meter, pill, list, grid, chips, prompt, marker, plate, progress, note, tip, drop target, window, text field, confirm). It draws and themes them, and it keeps movement, camera, input feel, combat timing, theme and layout. A skill with no `_ui()` gets a default derived from its spec and combat shape, so a world that declares nothing plays exactly as today. No new SpacetimeDB table is needed for the first steps. The first piece moved is the skill bar: `combat.rs`'s name matching and the step-4 WIP's guessed roles become declarations, and ui-1 step 4 is built on them.

## 1. Audit: where the interface comes from today

Sources: **rules** is `living/scripts/skills.rhai` or the `living_rules` crate. **table** is a row or view the authority publishes. **client** is code in `living/game/src`. **mixed** names both sources.

**Headline.** The tables below list 80 parts: 26 come from the rules or an authority table, 16 are mixed, 29 are client code, 4 are Rust outside the script and 5 are missing. The split is regular:
- **The rules decide what exists and what applies:** which skills, their costs and cooldowns, which acts fit a target, refusal reasons, sight radius, and recipes.
- **The client hard-codes how it looks, where it goes and how it is triggered:** icons, clips, effects, labels, keys, groups, window buttons, status thresholds and tip texts.

One fact shapes the whole design: **the client already compiles the world's rules script.** It subscribes to the public `script` row (`net.rs:88`, now 133 kB, not the "70 kB" its comment says), compiles it with the same `living_rules::script` the authority runs (`verbs.rs:92-115`), and runs each skill's `_check` locally to build the F list (`verbs.rs:252-346`). The mind service compiles the same row (`mind/src/prompts.rs:120-136`).

### Corrections to the first look

- **Skill bar: confirmed, with a correction.** The bar reads `skill_card` (`combat.rs:132-166`, written at install by `authority/src/combat.rs:572-606`). On main, though, keys go by slot position:
  - LMB/RMB, Q firebolt, E block, R heal, Shift dodge, Space jump (`combat.rs:454-471`); jump fires but is not drawn (6 places drawn, 7 bar skills).
  - The "rules' roles" (Q block, E heal, R fire bolt) exist only on `ui-1-step4-wip`, where `Roles::of` guesses them from `aim` and a client `BOLT_RADIUS` of 0.25.
- **The F menu: confirmed, but not through a table.** There is no table or view of available acts. The client runs the rules' `_check` on facts it builds itself, and some of those facts are faked: terrain grass, noon and age 30 (`verbs.rs:571-607`), summer (`:316`), and a target assumed to hold whatever is asked of it (`:307-312`).
- **Sight: only the radius is a law** (`skills.rhai:68-88`). Line-of-sight blocking is Rust: which tiles block (`rules/src/map.rs:57-59`) and the tile walk `Map::sight_clear` (`map.rs:316-325`). The cone is a client mock that is off (`sight.rs:20-67`). The camera is bounded by the mock's 11 m rather than the law's answer (`camera.rs:442-443`).
- **Ways of speaking:** on main they are a client constant (`talk.rs:36-44`). `speech_card` exists only on the unmerged `speech-1`, and nothing in the client reads it there.
- **`combat.rs` names: confirmed.**
  - `look()` matches 10 skill names, in 9 arms, for clips, icon and effect (`combat.rs:186-210`), and falls back on `aim` and `radius` for any other skill (`:200-208`).
  - Further name matches: `skill == "jump"` (`combat.rs:502`), the gestures (`town.rs:88-92`) and the act icons (`ui/verbs.rs:167-181`).
- **Keys: half right.** `keys.rs` is a full rebindable table with presets and a settings file, and Settings › Controls edits it. But on main `combat.rs:396-471` and `controls.rs:251-263` read raw key codes, so rebinding fighting and movement does nothing. The WIP branch fixes these consumers.
- **Hand-written windows: confirmed.**
  - The pack, the person window's buttons, the bars and the status pills are written per system.
  - So are the tips and the death screen.
  - `Win` is a closed enum (`ui/win.rs:49-56`).

### Skills and the bar

| Part | Source | Where | Note |
|---|---|---|---|
| Which skills are combat skills, and their traits | rules | `skills.rhai:1147-1183`; `rules/src/script.rs:1017-1076` (`KNOWN` at :1028) | Unknown trait refused at install. |
| Which skills are on the bar, in order | rules | `skill_bar()` `skills.rhai:1185` → `skill_card.slot` (`authority/src/combat.rs:587`) | `use_skill` refuses off-bar skills (`authority/src/combat.rs:626`). |
| Cost, windup, recovery, cooldown, reach, aim, radius, arc, needs, knows | table | `skill_card` `tables.rs:991-1024` | Computed for a newcomer person. No label, about, `hostile` or `evades`. |
| Key per slot (main) | client | `combat.rs:395-471`, `ui/live.rs:324`, `ui/model.rs:127-150` | Raw key codes; ignores `keys.rs`. |
| Key per slot (WIP) | client | `ui-1-step4-wip` `combat.rs` `Roles::of` | Guessed from aim and radius. |
| Icon and its colour | client | `combat.rs:186-210`; `ui/model.rs:154-162` (6 glyphs and an empty slot); `ui/theme.rs:33-45` | By skill name, else by aim and missile radius. |
| Cooldown sweep | table | `my_readiness` (`authority/src/combat.rs:719-722`) | Drawn by the client. |
| "Unavailable" reason | mixed | `ui/live.rs:267-296, 337-344` | `needs` and `knows` come from the card; the words "No arrows", "Unknown" and "Too tired" are the client's. The rules' own refusal (`my_combat` REFUSED note) is stored in `combat.rs:311` and never drawn. |
| Tooltip or description | missing | — | `_spec().about/takes/gives` exist, but no bar reads them. |
| Labels in Settings › Controls | client (main) | `ui/settings.rs:57-95` | On main `SkillNames` is never filled (`Roles` exists only on the WIP), so the rows read "Mouse skill", "Skill 1"–"Skill 3", "Jump", "Dodge". |
| Sheathe and draw | client (WIP) | `ui-1-step4-wip` `weapon.rs` | Local state only; `send()` is a no-op. No drawn state exists on any branch. |

### Combat presentation

| Part | Source | Where | Note |
|---|---|---|---|
| Clip per move, and its rate | client | `combat.rs:186-210, 581-621` (`BEATS` :595-601) | By name; the peak is timed to the card's windup. Animals: by aim (`combat.rs:562-568`). |
| Effects (slash, bolt, ring, guard arc) | mixed | `vfx.rs:177-265` | Event kind from `my_combat`; slash or bolt from `look()` by name. |
| Missile flight | table | `my_combat` LAUNCH/IMPACT | |
| Aim indicators | mixed | `combat.rs:686-740` | Shape from the card's aim, reach and arc; colours from the client. |
| Health band words and thresholds | rules (Rust) | `rules/src/combat.rs:224-261` | Rust in the rules crate, not script. |
| Hostile window (15 s) | client | `combat.rs:547-556` | The same 15 s is a literal in `heal_check`'s ally test (`skills.rhai:1256`), not a named rule. |

### Acts on things and people

| Part | Source | Where | Note |
|---|---|---|---|
| Candidate skills | rules | `*_spec` `skills.rhai:1642-1825`; `SPEC_TRAITS` `script.rs:1857` | The client compiles them. |
| Which act fits which target | mixed | `verbs.rs:252-346` runs the rules' `_check` | Client filters: real_time out; an unchecked skill only toward a person; `graph` args out; `want` args expanded. |
| Facts fed to the checks | client | `verbs.rs:571-625` | Noon, summer, grass, age 30; `near_fire` only for "campfire". Lit and fuel are never set, so `make` is never offered at a burning furnace. |
| Row labels | mixed | `verbs.rs:207-209, 341, 354`; `ui/verbs.rs:95-100` | Skill name with `_` replaced by a space. Specs have no `label`. |
| Row icons | client | `ui/verbs.rs:167-181` | Name match: give, offer, wave, nod, appraise, teach… |
| Grouping ("give ›", "Trade") | client | `verbs.rs:380-419`; `ui/verbs.rs:112` | Any `want` choice is forced into a group named `offer`. |
| Tap default | mixed | `verbs.rs:423-441` | Uses the rules' `force`/`hostile`/`menace` and `_shows().faces`. |
| The act sent | table | `human_act(node)` `authority/src/lib.rs:539-555` | Toward a person or oneself: `acts::submit`, the path minds use (`mind_act`, `authority/src/mind.rs:409-418`). Toward a thing the client sends `seq[goto, act]` (`verbs.rs:183-186`), which runs as a one-off behaviour through `mind::set_graph` (`lib.rs:553-554`). Quantity is always 1 (`verbs.rs:171-179`). |
| Outcome note | mixed | `verbs.rs:1116-1192` | The client parses the authority's English prefixes (`authority/src/acts.rs:42, 94, 100-103`). |
| Gestures G, B, V | client | `game/src/town.rs:36-42, 88-92` | Skill names and reach copied from the specs. |
| How an act looks to others | mixed | `_shows` `skills.rhai:1879-1908` → `act_card`/`doing` | The client matches 19 names first (`game/src/town.rs:96-109`), then the card's `look`. `give`, `offer`, `make` and `feed` have no `_shows`. |
| Person window buttons | client | `ui/people.rs:237-249, 330-347` | Five fixed buttons; not from the `talk: true` specs. |

### Speech

| Part | Source | Where | Note |
|---|---|---|---|
| Ways of speaking (main) | client | `talk.rs:36-44` `MODES` | person, room, whisper (greyed). |
| Ways (`speech-1`) | rules → table | `<way>_speech()` (`speech-1` `skills.rhai:116-119`) → `speech_card` (`speech-1` `authority/src/speech.rs:237-262`) | `WAY_TRAITS` at `speech-1` `rules/src/script/speech.rs:87-90`. Not read by the client. |
| Row texts heard | rules (`speech-1`) | `speech-1` `script/speech.rs:60-68` (fields), defaults in `WaySpec::say()` `:97-120` | The shipped `say_speech()` overrides none. On main, Rust strings (`perceive.rs:310-329`). |
| Refusals | mixed | `speech-1` `authority/src/speech.rs:41-108` | Rust formats over the way's name, plus the way's `_check`. |
| Max characters, Tab, Enter | client | `ui/say.rs:24, 68, 82` | On main Tab ignores its binding. |
| Box labels and hints | client | `talk.rs:213-220`; `ui/people.rs:258, 285` | |
| "Said to you" detection | client | `talk.rs:267` | Matches `" said to you:"` in the text. |
| Kinds drawn as talk | client | `heard.rs:24-47`, `ui/live.rs:163` | "speech", "said", "silence", "introduced". A `whisper` row would show nowhere. |
| Heard by | missing | `heard.rs:23-27` stub | `my_heard` exists on `speech-1`. |

### Items and the pack

| Part | Source | Where | Note |
|---|---|---|---|
| Item list | rules | `items()` `skills.rhai:199-213` | Name plus free traits (any key parses: `script.rs` `kinds_of`). |
| What I carry | table | `my_inventory` `perception.rs:815-819` | |
| Icon | client | `ui/icons.rs:78-109` | By substring of the name: Cullet's kelp, ash, sand, glass and peat all show as a bundle. |
| Label | client | `ui/mod.rs:149-156` | `_` replaced by a space and capitalised. Cells show no name. |
| Grid | client | `ui/pack.rs:25, 80` | 30 fixed cells. |
| Carry limit | mixed | `ui/verbs.rs:147-150` calls `carry_limit` | Wrong with a basket: the rules' `pack_full` adds 20 (`skills.rhai:251`). |
| Food value | mixed | `ui/verbs.rs:141-146` | Computed, then never drawn. |
| Drag onto a person | mixed | `ui/pack.rs:132-160`; `verbs.rs:968-985` | Takes the first peaceful choice with an item; the ghost always says "Give". |

### Needs and bars

| Part | Source | Where | Note |
|---|---|---|---|
| Values | table | `my_vitals` `perception.rs:794-798` | |
| Which bars | client | `ui/frame.rs:120-135`; `ui/live.rs:149` | Health and energy only. `max_energy` is fixed at 100. No hunger bar; cold and wet are not shown. |
| Status pills and thresholds | client | `ui/live.rs:128-146`, drawn in `ui/frame.rs:245-270` | Hungry 80, starving 97 and exhausted 12 copy the AI alerts in `brain.rs:865-871`; tired 35 is the client's own. The rules' `body_state` says hungry above 50 and starving at 100 (`skills.rhai:298-303`): three sources. |

### Crafting and recipes

| Part | Source | Where | Note |
|---|---|---|---|
| Recipes | rules | `recipes()` `skills.rhai:647-659` (shipped empty); Cullet `seeds/worlds/cullet/laws.rhai:226-234` | A script data table. No Rust struct and no table. |
| `make` | rules | `make_spec` `skills.rhai:1707-1711`; `make_check` `:690-707` | Items from `products()`. |
| Offering `make` at a workplace | mixed | `verbs.rs:252-297, 623-625` | Never offered at a fire that burns fuel: lit and fuel are left at their defaults. |
| Recipe window | missing | — | "Recipe" in the client means a character look (`characters.rs:103`). |
| Workplace look | client | `world.rs:576-603` | By name; the hearth always glows. |
| Three making systems | rules | `craft` `:515-615`, `make` `:647-729`, `cook`/`smoke` `:453-478` | Only `make` reads a recipe table. `cook`/`smoke` read the item traits `cooks_to`/`smokes_to` but hard-code fire and technique; `craft` uses the `cost()`/`made_by()` switches. |

### Storage

| Part | Source | Where | Note |
|---|---|---|---|
| Store and take rules | rules | `skills.rhai:759-785, 1692-1701` | Kinds by name ("storage", "remains", "trap"). |
| Contents | missing | `inventory` private; `my_inventory` is mine only | Minds see contents (`perceive.rs:682-685`). The client offers "take X" for every item in the world. |

### Trade and offers

| Part | Source | Where | Note |
|---|---|---|---|
| Offer, accept and terms rules | rules | `skills.rhai:1283-1307, 1364-1382, 1774-1788` | |
| The swap itself | Rust | `authority/src/act.rs:1430-1479` | English percepts written in Rust. |
| An incoming offer | missing | `act.rs:1442` writes kind "offer" | No client code draws that kind, so a player never sees an offer. `trade_offer` is private. |
| Making an offer | mixed | `ui/people.rs:238-239, 338`; `verbs.rs:272-275` (what I offer), `:339-344` (one want per catalogue item), `:381-397` (grouping) | Every catalogue item becomes a want, with quantities of 1. |
| Agreements | table | `my_records` `records.rs:487-508` | The client does not subscribe to it. |

### Knowledge and techniques

| Part | Source | Where | Note |
|---|---|---|---|
| Technique list | rules | `know_how()` `skills.rhai:948-974` | |
| What I know | table | `my_know_how` `perception.rs:820-824` | |
| K window | mixed | `ui/verbs.rs:152-163`; `ui/pack.rs:247-265` | Lists every spec, including `listed: false`. Never shows the technique's `help`. Hides any source containing "newcomer". |
| Ask to be taught | client | `verbs.rs:350-356` | The sentence "Would you teach me {t}?". |
| Teach check | rules | `teach_check` `skills.rhai:995-1018` | Checks against `techniques()` (what experimenting can reveal, `:1032-1044`), not `know_how()`, so the shipped fire_bolt and wound_tending, and Cullet's glassmaking (`seeds/worlds/cullet/laws.rhai:222`), cannot be taught (read, not run). |
| Tablets and signs | table (private) | `artifact` `tables.rs:617-628` | No client view. `write` never sends a topic (`verbs.rs:165-188`). |

### Sight

| Part | Source | Where | Note |
|---|---|---|---|
| Radius | rules | `senses()` `skills.rhai:68-88` | The client re-runs it with kind, pack and the hour's light only (`sightedge.rs:158-181`). |
| Blocking | Rust | `rules/src/map.rs:57-59, 320` | No law can change it. |
| Who is perceived | table | `perception.rs:432-499` → `seen_*` views | |
| Name or label | table | `perceived_of` (`skills.rhai:114-123`) decides the name; the label words are Rust (`perception.rs:269-282`) | "in red" is the client's own (`looks.rs:106-160`). |
| Edge look | client | `sightedge.rs:37-112` | F2 is a raw key. |
| Cone | client mock | `sight.rs:20-67` | Off. Facing never reaches the authority: `human_face` is not on main (dev-box's fov-1 builds it), so `controls::look` is a no-op (`controls.rs:302-321`). |

### Tips and hints

| Part | Source | Where | Note |
|---|---|---|---|
| Tip text | client | `ui/tips.rs:13`; `ui/prompt.rs:100-101`; `controls.rs:65-70`; `sightedge.rs:73-83` | Key names written into the strings. |
| Triggers | client | `talk.rs:241-271`; `controls.rs:156-193`; `sightedge.rs:228-235` | Each system has its own; the talk tip matches text. |
| F prompt | mixed | `ui/prompt.rs:145-160` | The key comes from the bindings; "Talk" is fixed; a thing gets the likely act's label. |

### Death

| Part | Source | Where | Note |
|---|---|---|---|
| What death does | Rust | `authority/src/act.rs:2179-2257` | Remains are always left for a person. The rules give only `carcass` and `remains_s`. No `on_death` is shipped. |
| Cause | Rust | `brain.rs:141-146`, `tick.rs:415`, `act.rs:2064` | |
| Screen | client | `ui/death.rs:30-121`; `ui/live.rs:362-389` | The client re-maps causes by string ("starvation", "old age", "killed by "). |

### Gaps found on the way

These are not interface design, but declarations would bring them into view. They are listed so that a worker does not hit them blind.
- **A fuel-burning fire is never lit in the client's checks.** `thing_facts` leaves `lit` and `fuel` at their defaults (`verbs.rs:623-625`; `lit_until_ms` is never read), so `make` at Cullet's hearth, oven, furnace or smokehouse is never offered. Campfire recipes still are.
- **Teaching:** fire_bolt, wound_tending and Cullet's glassmaking cannot be taught (`skills.rhai:995-1044`).
- **The pack's limit** is 20 short with a basket.
- **Offers:** a player is never shown an incoming offer.
- **Bar refusals:** the rules' refusal reason is stored but never drawn.
- **Rebinding:** rebinding fighting and movement does nothing on main.
- **The camera** follows the mock's sight, not the law's.
- **`listed: false`** hides a skill from minds but not from the player's K window.
- **`cadence`** in a law is required and checked, but the engine never reads it (`script.rs:1284`). Caching is decided per law in Rust (`script.rs:1376-1435`).

## 2. The primitives the client exposes

The client keeps a fixed vocabulary. The rules choose names from it, and only the client draws them. Each primitive is a Bevy UI node tree (`bevy_ui` 0.20.1, `living/game/Cargo.toml:8`), painted from the active theme and hit-tested by `ui/hit.rs`, the game's own cursor path. The vocabulary's names live in a new `living_rules::ui` module, so that install can check a declaration against them.

### What can be shown

| Primitive | What it is | Exists today as | Needs from Bevy |
|---|---|---|---|
| `bar` | The cluster's row of slots, filled by `place` and `order`, with an extra row when needed | `ui/frame.rs:139-175`; WIP `ui/cluster.rs` | `Node` row; spawned once per install and updated in place |
| `slot` | Icon, key chip, cooldown sweep, cost, count, greyed with a reason | `ui/frame.rs`; WIP `cluster.rs` `bar()`/`slot()` (local functions) | `Node`, a glyph `ImageNode` from `ui/icons.rs`, a text chip; the key label from `Binds::first` |
| `meter` | A bar showing value over maximum, with a tone | `ui/frame.rs:120-135` | `Node` width as a percentage |
| `pill` | A status with a tone: an icon today, with an optional word | drawn in `ui/frame.rs:104-114, 245-270`, from statuses computed in `ui/live.rs:128-146` | `Node`, a glyph `ImageNode`, optional `Text` |
| `list` | Rows of icon, label, key number and `›` for a sub-list | `ui/verbs.rs` | `Node`; a `ScrollPosition` node scrolled by `Pointer::scroll_px` (`pointer.rs`), as `ui/pack.rs:80-96` does |
| `grid` | Item cells with count and icon; a drag source | `ui/pack.rs` | `Node` grid; drag through `UiPointer.dragging` |
| `chips` | A row of choices; one picked; greyed with a reason | `ui/people.rs:202-206` (only the greyed whisper) | `Node` and `Text` |
| `prompt` | A label beside a thing or person in the world ("F Talk · hold F · more") | `ui/prompt.rs:145-160` | `Camera::world_to_viewport` (Text2d does not render with the 3D camera) |
| `marker` | On the ground: a circle, arc or line of a given radius | `combat.rs:686-740` | Gizmos or a decal mesh |
| `plate` | Over a head: label, band or exact health | `ui/overhead.rs` | `world_to_viewport` |
| `progress` | A ring or bar while an act runs | none (windups show only as clips) | `Node` |
| `note` | A rising message, green when done, red when refused, grey when an act begins | `verbs.rs:1104-1196` | `Node` and `Text` |
| `tip` | A first-time hint, with `{key}` replaced by the bound key | `ui/tips.rs`, `ui/prompt.rs:89-106` | `Node`; `Binds` |
| `drop_target` | A person, person window or thing outlined while an item that a `drag` declaration accepts is carried over it; the ghost names the act | `ui/pack.rs:132-160` (nearest head within 70 px) | `world_to_viewport`, `UiPointer.dragging` |
| `window` | A floating window built from the above, at the client's anchors | `ui/win.rs` | Existing |
| `text_field` | Words, a "to whom" label and a character limit | `ui/say.rs` | Existing |
| `confirm` | A two-button question | none; the nearest is Leave the world's click-again row (`ui/top.rs:10`) | `Node` |

### The input a rule can ask for

| Kind | The player… | Engine side |
|---|---|---|
| `tap` | presses once; a skill aimed at a creature takes the one under the cursor, else the nearest in reach | `pointer.rs` tap and hold; `pick.rs` (who is under the cursor), `combat.rs` pick |
| `hold` | holds; release ends it, as a guard does | `release_skill` on key up |
| `toggle` | presses to switch a body state (drawn or sheathed) | a binding; the state shows on its slot |
| `aim_point` | aims at a point within the spec's reach; a `marker` shows the reach | the ground point under the cursor; sent as `use_skill(…, x, y)` or `target: {"at": [x, y]}` |
| `aim_dir` | aims a direction; a `marker` shows the arc | cursor or facing direction |
| `pick_target` | picks the hovered target, or cycles with Tab within reach | `verbs.rs` aim; `talk.rs` earshot order |
| `pick_item` | picks from a sub-list of the pack, or from a declared list | `list` or `grid` |
| `pick_qty` | sets an amount, from 1 up to the amount carried | new: a stepper in the sub-list (today every quantity is 1) |
| `drag_onto` | drags an item onto a person, their window or a thing | `drop_target` |
| `words` | types words | `text_field` |

### Where a declaration attaches (`on`)

| Place | Meaning | How it is sent |
|---|---|---|
| `bar` | The skill bar | `use_skill` for a skill with `_combat()` in `skill_bar()`; otherwise the `human_act` node `{"do": name, …}` |
| `person` | F toward a person, and their window | `human_act` with `target: {"id": n}` |
| `thing` | F toward a resource or structure | `human_act` with `target: {"nearest": kind}`, wrapped in `seq[goto, act]` when not the nearest (`verbs.rs:183-186`) |
| `ground` | A point on the ground under the cursor (build, plant, pave) | `target: {"at": [x, y]}` |
| `self` | C, the acts on oneself | `human_act` with no target |
| `item` | Clicking an item in the pack | as for `self`, with that item |
| `box` | The ways chips in the text box | `human_speak(text, to, way)` |
| `offer` | An incoming offer or proposal | `human_act` toward its sender, `target: {"id": sender}`, with the offer it answers, `"offer": id` (docs/WORLD_RULES.md, "Answering") |

Declarations can add rows to two fixed window kinds: `person` (pinned acts) and `skills` (descriptions). A new window kind is a client change (section 4).

### Named looks

The client's theme maps each name to assets. The lists live in `living_rules::ui`:
- **`icon`:** sword, bow, fire, shield, dodge, heal, sheath, give, trade, talk, wave, eye, book, hammer, pot, hand.
- **Item icons:** berries, bread, meat, arrow, spear, wood, stone, herb, torch, cloth, tablet, tool, vessel, bundle.
- **`clip`:** slash, overhead, thrust, shoot, cast, guard, dash, jump, bite, leap, gesture, work, eat, sleep, rest, hand. These are families, not file names: the client maps a family to its clips, rates and beats (`BEATS` stays in `combat.rs`).
- **`effect`:** slash, arrow, bolt, burst, glow, guard_arc.
- **`row`** (how a way's experience kind is drawn): line, dots, hidden.
- **`bubble`:** normal, hushed, none.

**Body states** (`STATES`, for a combat `stance`): drawn. Each state is added only when the authority has it.

## 3. How a rule or skill declares its interface

### Where it lives and how it travels

- **Where.** `<name>_ui()` sits beside `<name>_spec()`, `<name>_combat()` or `<name>_speech()`. It is a nullary function returning a map, like every other declaration (`script.rs:931-986`).
  - It is a separate function, not a `ui` key inside the spec, so that a seed's laws overlay (as Cullet uses) can restyle a skill without copying its rules.
  - `<name>` must be a skill with a spec or a way of speaking. A name that is both is refused.
- **Who reads it.** `living_rules::script` reads it at compile time into `UiSpec`, beside `SkillSpec` and `Shape`. One parser serves the authority's install, the client and the mind.
- **How it travels.** It travels in the `script` row, which every client already subscribes to and compiles. There is no new table in the first steps, for three reasons:
  - The client must keep the compiled script anyway, because the F list runs `_check`.
  - A typed card table would freeze its columns: automatic migration only adds columns at the end with a default.
  - A table would duplicate data the client already has.

  A `ui_card` table is the later option if the client ever stops compiling the script (section 7).
- **Strict at install, lenient in the client.** `Scripts::with_day` fails on any declaration error today (`script.rs:968-979`), and a client that cannot compile the script drops every rule (`verbs.rs:105-110`): the F list goes empty. So:
  - `with_day` reads every `_ui()` leniently. Each problem goes into a `ui_errors` list, as `law_errors` already works, and that `_ui()` falls back to its defaults.
  - `validate()`, which only the authority's install calls, refuses a script with any `ui_errors`, so a bad world never installs.
  - The client logs `ui_errors` once and plays on with the defaults. Presentation alone can never empty the rules.

### Fields (`UI_TRAITS`)

| Key | Value | Default when absent |
|---|---|---|
| `label` | Short display name ("Fire bolt"). For a way, only `_speech()` sets it | The name, with `_` replaced by a space and capitalised (as now) |
| `on` | One place or a list (section 2); never empty (hide a skill with `listed: false`) | `bar` for a skill in `skill_bar()`. Otherwise from the spec, unless real-time combat: `person` (and `thing` when checked) if `target`, `self` otherwise, and `item` for a pack item with no target |
| `place` | For the bar: `primary`, `secondary`, `skill`, `jump`, `dodge`, `weapon` or `extra` | By aim, as the WIP's `Roles::of` does now, but computed in `living_rules::ui` |
| `order` | A number: position within its place or list. For a way, only `_speech()` sets it | Script order |
| `input` | An input kind (section 2) | From the combat aim: creature → `tap`; self_or_ally → `tap`, on the hovered ally, else oneself; point → `aim_point`; facing → `hold`; dash → `tap`. Otherwise `tap` |
| `picks` | What must be chosen. `target` needs a spec with `target: true`; `item` needs `item`; `qty`, `want` and `words` need those args (`qty`, `want`, `text`) | From the spec |
| `choose` | How an item is chosen: `list` or `grid` | `list` |
| `detail` | The name of a script function that takes a choice's name and returns a text describing it | none |
| `unready` | What a press does while the skill's combat `stance` is not met: `toggle` (the press switches the state instead) or `grey` | `grey` |
| `toggles` | The body state this declaration switches | none |
| `drag` | Dropping an item on this target does this act: `person` or `thing` | none |
| `pin` | Shown as a button in the person window | false |
| `running` | `#{ show: "windup" \| "progress" \| "held" \| "none", text }` | `windup` for timed combat, `held` for a guard, `progress` for a `latch` skill (work not dropped half-done) |
| `refused` | `grey` or `note` (see below) | `grey` on the bar, `note` elsewhere |
| `look` | `#{ icon, clip, effect }`; `clip` may be a list | `icon` and `effect` by aim, as `combat.rs:200-208` does now. `clip` is the skill's `_shows().look` if it has one, else by aim |
| `marker` | `circle`, `arc`, `line` or `none` | From the aim |
| `key` | A suggested default key, used only if the viewer has not bound that act | none |
| `tip` | A first-time hint, with `{key}` | none |
| `alias`, `to_label`, `room_label`, `rows`, `bubble` | For ways of speaking only (see the whisper example) | the say defaults |

What `refused` means:
- **`grey`:** when needs, knows, cost or cooldown change, the client runs the skill's `_check` on its own facts, as the F list does (`verbs.rs:303-318`). A refusal greys the slot, and the check's text is the tooltip, with `about` and `takes` under it. A skill with no `_check` is never greyed.
- **Either way,** a refusal that still comes back from the authority is drawn as a `note`: `my_combat`'s REFUSED note, or the act's outcome.

Checks at install. Unknown keys are refused when the script is compiled, naming the function and listing the accepted keys, as `spec_of` does (`script.rs:1879-1880`): `strike_ui: unknown trait 'slot' (traits are label, on, place, …)`. Then `validate()` (`script/check.rs:98-344`) checks:
- **Known names:** every look, place, input and state name is in its vocabulary.
- **Consistency:**
  - `on: "person"` or `"thing"` needs a spec with `target`;
  - `picks` must match the spec, as in the field table;
  - `input: "aim_point"` needs a combat aim of point, or a spec with `target`;
  - `on: "bar"` on a combat skill needs it in `skill_bar()`;
  - a declared `clip` may not contradict the skill's `_shows().look`.
- **References:**
  - `detail` is called on each name in the spec's `items` and must return a text;
  - no two skills claim the same single bar place (`primary`, `secondary`, `jump`, `dodge` or `weapon`).
- **Other tables:**
  - an item's `icon` trait must be an item icon, and its `group` one of food, tool, material, garment or money;
  - `meters()` rows must name `my_vitals` fields;
  - `status_of` is called on sample actors and must return a list of `#{ name, tone, text }`.

### Five declarations

**1. Sword strike, with sheathe and draw.** This is the owner's attack rule: X sheathes or draws; a tap strikes only while drawn; the weapon draws itself when you are attacked; while sheathed, the first press of an attack draws instead.

What it needs from the rules. "Needs the weapon drawn" changes what a body may do, so it is a rule: a combat trait `stance` that the authority enforces in `use_skill`, for players and minds alike. Drawing is a deliberate act that takes the state it sets, so a mind's graph that runs it each tick changes nothing, and a toggle never flips back and forth. This is the end state, once the Spark adds the drawn state:

```rhai
fn strike_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true,
                        melee: true, closes_in: true, force: true, dares: true, knack: "attack", stance: "drawn" } }
fn strike_ui() {
    #{ label: "Strike", on: "bar", place: "primary", unready: "toggle",
       look: #{ icon: "sword", clip: ["slash", "overhead", "thrust"], effect: "slash" },
       running: #{ show: "windup" }, refused: "grey" }
}
// The weapon in hand or put away: a body state, set the same way by players and minds.
fn draw_spec() {
    #{ item: "state", items: ["drawn", "sheathed"],
       about: "Draw your weapon, or put it away (item: drawn or sheathed). Drawn, others see you are ready to fight; blows need it drawn.",
       takes: "a moment", gives: "your weapon in hand, or sheathed" }
}
fn draw_ui() {
    #{ label: "Weapon", on: "bar", place: "weapon", input: "toggle", toggles: "drawn", key: "X",
       look: #{ icon: "sheath", clip: "hand" },
       tip: "{key} draws or sheathes your weapon. Sheathed, a tap never strikes; it draws itself if you're attacked." }
}
```

How these behave:
- **The weapon slot.** It is not a combat skill, so the slot sends `human_act {"do":"draw","item":"sheathed"}` or `"drawn"`. The WIP's `weapon::act` must send that shape (today `{"do":"draw"|"sheathe"}`).
- **A tap on a peaceful person.** A tap on a person runs the `primary` skill. When its `stance` is not met and `unready` is `toggle`, the tap opens talk; any other press draws. This is the "tap talks while sheathed" rule, derived from the declarations rather than from `kind == "person"`.
- **Drawing when attacked.** This is a player setting, as Settings › Play already holds it. A mind draws through its own acts or graph; there is no engine reflex.
- **Until the Spark adds the drawn state** (with its act, the `stance` trait and the projection field):
  - `draw_spec`, `draw_ui` and the `stance` trait do not ship;
  - `weapon.rs` keeps `drawn` locally on the Weapon binding, gating the `hostile` bar skills as the WIP does;
  - `strike_ui` ships without depending on it.

  Then `weapon::send` sends the act, `weapon.rs` reads `stance` and `toggles` instead of `hostile`, and nothing else in the client changes.

**2. Fire bolt.**

```rhai
fn firebolt_ui() {
    #{ label: "Fire bolt", on: "bar", place: "skill", order: 2, input: "aim_point", marker: "circle", unready: "toggle",
       look: #{ icon: "fire", clip: "cast", effect: "bolt" },
       running: #{ show: "windup" }, refused: "grey" }
}
```

- **Key.** `order: 2` puts it on the third skill key (R by default, 3 in the numbers preset). Block gets `order: 0` (Q) and heal `order: 1` (E). This settles the disagreement between main and the WIP in the script, where a world can change it.
- **Greying.** The grey runs `firebolt_check` ("you don't know how to hurl fire …") with the cost and cooldown from `skill_card`. The tooltip is that text, then `firebolt_spec().about` and `takes`. A refusal from the authority is drawn from `my_combat`'s REFUSED note, which is never shown today.
- **Stance.** Whether a fire bolt needs the weapon drawn is the world's rule: `stance: "drawn"` in `firebolt_combat()`, or not. `unready` only matters when it does.

**3. Giving an item.**

```rhai
fn give_ui() {
    #{ label: "Give", on: ["person", "item"], picks: ["target", "item", "qty"], choose: "list", drag: "person", pin: true, order: 0,
       look: #{ icon: "give", clip: "hand" }, refused: "note" }
}
```

- **Entry points.** One declaration gives:
  - the F list row "Give ›" toward a person, and the "Give" button in their window (`pin`);
  - a pack item's "Give to…";
  - the drag of an item onto a person (`drag`), with the `drop_target` outline and the ghost "Give berries to a stranger in orange".
- **What it replaces.** It replaces four hand-written pieces:
  - the button (`ui/people.rs:238`);
  - the `gifts()` filter (`ui/people.rs:367-369`);
  - the drag's "first peaceful choice" (`verbs.rs:968-985`) and its fixed ghost text;
  - the icon match (`ui/verbs.rs:169`).
- **Quantity.** `qty` adds a `pick_qty` stepper.
- **The check and the act.** The check is still `give_check`, and the act is still `{"do":"give","target":{"id":N},"item":…,"qty":n}` through `human_act` and `acts::submit`.

**4. A recipe at a workplace** (goods-1's `make`).

```rhai
fn make_ui() {
    #{ label: "Make", on: "thing", picks: ["item"], choose: "grid", detail: "made_how",
       running: #{ show: "progress", text: "Making {item}" },
       look: #{ icon: "hammer", clip: "work" }, refused: "note" }
}
// In a world's goods (Cullet's laws.rhai), the icon is an item trait, read by the pack and by this grid:
//   #{ name: "glass", icon: "vessel" }, #{ name: "ash", alkali: true, icon: "bundle" }
```

How it works at a furnace:
- **The grid.** F at a furnace offers "Make ›", which opens a `grid` of the products:
  - A product whose `make_check` passes is a live cell.
  - A product that passes only when the check is run again with the recipe's inputs added to my pack is a greyed cell, with the real check's text as its reason. The client already assumes a target holds what is asked, at `verbs.rs:307-312`.
  - Each cell shows the product's `icon` trait. Its `detail` is the rules' own `made_how(item)`, which wraps `recipe_words(recipe_for(item))` (`skills.rhai:1603-1615`): "make it at a furnace from 1 alkali and 2 sand and 1 fuel from it (knowing glassmaking)".
- **While it runs:** a `progress` ring for the recipe's `ms`.
- **A precondition.** The client must set `lit` and `fuel` on a structure target from `structure.lit_until_ms`, the kind's `burns.rate` and the world's `day_ms` (`living_rules::fire`). Without that, no fuel-burning workplace ever offers anything.

**5. Whispering** (speech-2). The shape follows `speech-1`'s `WAY_TRAITS`, not the older map in `COMMUNICATION.md` §3, which `speech-1` would refuse.

```rhai
fn whisper_speech() {
    #{ label: "Whisper", order: 1, about: "Whisper to someone beside you. Only they hear the words; people nearby who see you may notice that you whispered.",
       words: #{ within_m: 1.5, only_to: true }, to: "required", reach: 1.5, kind: "whisper",
       noticed: #{ within_m: 6.0, seen: true, kind: "whispered", text: "{a} whispers something to {b}." },
       said_to: "You whispered to {b}", heard_to_you: "{a} whispers to you", gap_s: 2.0 }
}
fn whisper_ui() {
    #{ on: "box", alias: "/w", to_label: "Whisper to {b}", bubble: "hushed",
       rows: #{ whisper: "line", whispered: "dots" } }
}
```

How the box uses it:
- **Chips.** The box's chips are the ways in their `_speech()` `order`, with their `label`.
- **Greying.** The whisper chip greys by the client's distance against `reach` and its know-how against `needs`. Its words are the way's own script check (`whisper_check`, being built by `speech-1`), which the client runs before sending, as the F list runs `_check`; they stay in the script, not in Rust (the Spark, 2026-11-11).
- **Rows.** `rows` says how to draw the kinds this way declares, its `kind` and `noticed.kind`:
  - `whisper` is a line with words in the log, with a hushed bubble;
  - `whispered` is "…" between the two people.
- **The primitive's own kinds** (`said`, `silence`, `repeat`, `introduced`, `signal`) stay a fixed client vocabulary. `talk.rs:267`'s text match is replaced by the row's `object` being me.
- **Defaults.** `say_ui()` would set `room_label: "Say to everyone nearby"` and `to_label: "Say to {b} (others nearby hear)"`. Without it, those are the defaults.

### Declarations that are not skills

These are kept small and follow the same rule: data in the script, read at compile, defaults when absent.
- **Meters and statuses.** These go in a `meters()` table: `#{ name: "health", value: "hp", max: "max_hp", order: 0 }` and `#{ name: "energy", value: "energy", max: 100.0, order: 1 }`. A `status_of(a)` law returns `[#{ name: "hungry", tone: "warn", text: "Hungry" }, …]`.
  - The client calls it when a `my_vitals` row changes, replacing the pills' fixed thresholds.
  - If the AI alerts in `brain.rs:859-871` move onto it, there is one source instead of three. It must then be memoised per state, as `senses` is (`script.rs:1376-1398`), and its tick cost measured at 216 characters.
- **Items.** `icon` and `label` become item traits (they already parse), plus an optional `group` (food, tool, material, garment, money) that orders the pack.
- **Tips.** A `tip` on a declaration is shown once per session, the first time its place becomes usable, with `{key}` resolved from the bindings. The client's arrival notes for F2 and F3 stay client tips: they are about the client, not the world.
- **Bindings for declared skills.** A gesture or any skill with a `key` gets a binding `Act::Skill(name)`, saved by name in the settings file and ignored when the world has no such skill. The fixed `Wave`, `Nod` and `LookOver` acts stay as aliases until it lands.

## 4. What stays in the client

The line: **the rules decide what a character may do; declarations choose which primitive, where, with which input kind and which named look; the client decides how it feels, how it looks and where it sits on screen.**

The client keeps:
- **Movement and camera:** steering prediction, the camera, and the bounds the camera keeps (fixed to follow the law's sight, not the mock's).
- **Input feel:**
  - thresholds: tap against hold (`pointer.rs:40`, `verbs.rs:42`), the double-tap window (`keys.rs:24`);
  - press buffering and mouse capture;
  - which person "under the cursor" means (`pick.rs`: the front-most body whose outline holds the cursor; `combat.rs` pick).
- **Combat timing:**
  - starting the clip on the press, before the authority answers;
  - aligning a clip's peak to the windup (`combat.rs:581-621`);
  - hit reactions, corpse time and floating numbers.

  The 60 Hz target and the local-latency rules in the performance contract cannot wait for a script call.
- **The theme:** colours, fonts, frames, density, glyphs, cursor, and which icon file or clip a name maps to. Play-test 4 asked for two or three clean themes, switchable. A theme is a client resource mapping the vocabulary of section 2, so a world never names a colour or a file.
- **Layout:** the anchors and window sizes (`ui/win.rs:33-46`), the cluster's arrangement, row limits, scaling, and what happens when there are more skills than places (extras spill into the skills window).
- **The player's conveniences:** bindings, saved in the local settings file (a declaration's `key` is only a suggestion), and the weapon drawing itself when attacked.
- **Developer tools:** the F1 panels, the F2 and F3 switches, and the live-script steps.
- **The client's own windows:** Settings, Menu, the compass and the death screen's frame. A new window kind is a client change.

**Why the line falls here:**
- Frame time and latency: a press must answer in the same frame.
- Themes must swap without touching worlds.
- The script is world data shared with minds, so it must not depend on one client's pixels.
- A client must render any world safely: names from a fixed vocabulary can always fall back, and code cannot.
- Whatever limits a character is enforced by the authority for both controllers (AGENTS.md: shared capabilities, rules authoritative in the authority). A declaration only says how to offer it.

## 5. One description for players and minds

One declaration feeds three readers, through one parser:

```text
give_spec() + give_check() + give_ui()
   │
   ├── mind:   catalog::skill_line → "- give(target, item, qty): Hand items from your pack to someone beside you. …
   │                                     takes: the items from your pack, room in their pack
   │                                     gives: the items in their pack"
   ├── player: UiSpec → F row "Give ›", the person window's Give button, the drag onto a person, the pack's "Give to…";
   │           tooltip = the same about / takes / gives
   └── both:   give_check (the client's guess, the authority's decision) → human_act / mind_act → acts::submit
```

Rules that keep the two controllers from drifting:
- **A declaration cannot add a capability.** Every `_ui()` names a skill spec or a way of speaking.
  - A skill's `picks` must map onto its spec, so what the player sends is an act node that `graph::parse` also accepts from a mind.
  - A way's `_ui()` only restyles what its `_speech()` already enforces (`to`, `reach`, `needs`).
  - Requirements such as `stance` live in the combat shape or `_check`, which the authority enforces for both.
- **One filter decides what is offered.** A new `living_rules::ui::offered(&Scripts)` serves both the mind's `skills_help_of` (`catalog.rs:331-333`) and the client's `skills_of` (`verbs.rs:86-88`).
  - `listed: false` then hides a skill from both. Today graze shows in the player's K window.
  - Real-time is one definition: `Shapes::real_time`, which counts `moment` (`rules/src/combat.rs:181-183`), not the client's combat-only check (`verbs.rs:255`).
  - Players commanding moment skills (sleep, rest, follow) through a one-shot graph is a shared capability (`authority/src/lib.rs:544-556`) and stays. Minds do the same in their graphs.
- **One text.** The player's tooltip and the mind's option line are the same `about`, `takes` and `gives`. `label` is presentation only; minds keep the name, which is what acts are written with.
- **One refusal.** A greyed slot's words and a refused act's note are the rules' `_check` result, the same text a mind receives as failure feedback. Client-made reasons ("Unknown", "Too tired") go.
- **A test.** A rules-crate unit test asserts that for every spec, the act nodes the default `UiSpec` would build parse under the mind's grammar, and that `offered()` gives the same set to both.

Not in scope here, but on the same path: the mind's hand-written `ACTS` and `TALK_SHOWN` (`mind/src/prompts.rs:91, 277-292`) and its fixed `Kinds:` line (`:249`), which misses goods-1's structures, should be generated from the same specs.

## 6. The path from here

Each step leaves the game playable. A step that ships no declarations changes nothing for the player. ui-1's steps 4 and 5 are steps 2 and 3 here.

**Step 1: the vocabulary and defaults, in the rules crate.**
- **`living_rules::ui`:** `UiSpec`, the vocabularies of section 2, and `defaults(spec: &SkillSpec, shape: Option<&Shape>, missile: Option<&MissileSpec>)`.
  - The defaults are the client's current guesses, moved into the shared crate: `look()`'s aim fallback for icon, clip and effect, with `BOLT_RADIUS` 0.25 as the line between an arrow and a bolt; and the spec-derived `on` and `picks`.
  - `bar_places(&Scripts)` keeps the WIP `Roles::of`'s resolution across the whole bar: places in their order, and the first unused skill whose aim fits each. Declared places come first.
- **`Scripts::ui(name)`:** the declared `UiSpec`, or the default, with the lenient read and `ui_errors` of section 3.
- **Shipped declarations:** look-only `_ui()` for `strike` (three clips), `shoot` (a bow, no slash) and `throw` (its own clip), the three the client drew by name that no shape can derive. No place or key changes.
- **Owner:** the rules crate is the Spark coordinator's. The laptop worker writes it and the Spark reviews.

**Step 1 as built** (`ui-decl-1`, 2026-11-11, after the Spark's review; not merged until the review is clean). Where it differs from the plan above, it says so.

**Module.** `living/rules/src/ui.rs` needs no script runtime; reading `_ui()` is `living/rules/src/script/ui.rs`. Rules code never reads `UiSpec`.
- **Vocabulary enums**, with `parse`, `as_str` and `ALL`: `On`, `BarPlace`, `Input`, `Pick`, `Choose`, `ItemSource`, `Unready`, `RunShow`, `Refused`, `Marker`, `Row`, `Bubble`.
- **Name lists:** `ICONS`, `ITEM_ICONS`, `CLIPS`, `EFFECTS`, `STATES`, `ITEM_GROUPS`, `UI_TRAITS`.
- **Every list is append-only.** A golden test (`the_vocabulary_only_grows`) refuses a rename or reorder, so a world installed with a name keeps installing.
- **Changes from section 2:**
  - `On::Offer` is new: toward an incoming offer's sender.
  - The `person` pick is `target`, and the `pick_person` input is `pick_target`.
  - `Pick::Topic` is new, for `write`.
  - `source` (`ItemSource`) says where an item choice comes from: pack, techniques, signals, spec_items, target_holds, products or world.
  - `CLIPS` adds `throw`, `turn`, `step` and `play`, so every shipped `_shows().look` is a family.
  - `STATES` is empty until the drawn state lands, so any `toggles` is refused.
  - `effect: "none"` declares no effect.
  - Item `icon` and `group` traits are not checked at install: they are the dev-box's vocabulary.

**`defaults(&Source)`.** It reads the spec, the combat shape, a newcomer's missile, bar membership, whether a `_check` exists, and the `_shows` look. The plan's three-argument signature could not reproduce today's F list.
- **`on`:** as `verbs.rs` `plan()` offers.
  - Real-time combat off the bar is nowhere, by the client's combat-only test: attack, shoot and throw have no player entry, as today.
  - A spec with a `graph` arg is nowhere.
  - An unchecked target skill is `person` only.
  - `item` only for a pack item with no target (eat, drop, experiment).
- **Fight looks:** look, marker and input by aim only for a fight move, one on the bar or hostile. Tend, seize and yield get no sword.
- **`picks`:** from the spec. A combat skill aimed at a point takes its target from the aim, and a held guard takes no `qty`.
- **`running`:** `progress` for a `latch` skill, not "over 2 s", which would need sampled facts.

**`bar_places(&Scripts)` and `bar_places_of(&[BarEntry])`.** With nothing declared they place exactly as `Roles::of` did.
- Declared places come first.
- A skill key a declaration took passes its default skill to the first free key.
- A single place claimed twice keeps the first claim, and the install refuses the second.
- The keys follow the WIP and example 2 (Q block, E heal, R fire bolt), not main's slot order (Q fire bolt, E block, R heal). LMB, RMB, Shift and Space agree with main.

**One filter and one definition.**
- `offered(&Skills, Option<&Species>)` is the filter. `catalog::skills_help_of` and `species::skills_help_of` call it, so minds' references are byte-identical.
- `real_time()` is `Shapes::real_time_in`, which `Shapes::real_time` now calls.

**Act building.**
- `act_node()` is `verbs.rs` `Choice::node`, moved here; `Picked` adds `topic`.
- `ActTarget::Offer` names the sender and the offer it answers: `{"do": "accept"|"decline", "target": {"id": sender}, "offer": id}`, with `"offer"` left out when the id is 0 (test `an_act_toward_an_offer_names_it`). A proposal of terms is answered with `"record": id` (docs/WORLD_RULES.md, "Answering").
- `bar_act()` returns `Option`: the leaf a press means, resolved as `use_skill` resolves it, and `None` where the authority refuses. The equivalence covers intent and target only: a press is used where the body stands, while a leaf with `{"id": n}` walks into reach first.

**`Scripts`.** Methods `ui(name)`, `ui_specs()`, `ui_default(name)` and `ui_errors()`. `validate()` refuses any `ui_errors`, listing up to 12. The read keeps the default per field, so the rest of a declaration holds. Checks against the rules:
- `self` with a target spec, `ground` without a point aim, an empty `on` (hide a skill with `listed: false`), and `offer` without a target are refused.
- Inputs must pair: `toggle` with `toggles`, `hold` with a held shape, `aim_dir` with facing or dash, each `pick_*` with its pick, `drag_onto` with `drag`.
- `unready` is refused until a stance exists.
- `order` must be 0..12.
- `source` must fit the spec.

**Grey is a hint.** `Refused::Grey` and `Unready::Grey` grey a slot, but a press still goes to the authority. The client's `_check` runs on the facts it has, some faked today: noon, grass, age 30.

**Waiting on other work:**
- Ways (review finding 9): a way's `UiSpec` is built only from its `_ui()`. When speech-1 lands, every way gets a base from its `_speech()` (label, order), so ways with no `_ui()`, such as `say`, still appear.
- `toggles` (finding 10): once `drawn` exists, `toggles: "drawn"` must be among the setting skill's items and some shape's stance.

**Tests** (`rules/src/ui/tests.rs`). The oracles are frozen from main's `look()`, the WIP's `Roles::of`, `verbs.rs` `plan()` and `use_skill`'s target resolution.
- Looks, the bar (including 88 orderings and subsets), aims and lists reproduce today's game on the island and Cullet.
- Every default act parses for minds (`acts::parse`, `graph::from_value_for`) and through `human_act`'s `graph::parse`, with equal roots and the same skill, target kind, item, amount, want, words and topic.
- A bar press gives the leaf `use_skill` resolves, or both refuse.
- `offered()` matches minds' references for people and every species. `offered(None)` equals a person's, `listed: false` hides a skill from both, and real-time agrees with `acts::not_an_act` for every name.
- The same facts give a player's act and a mind's the same `_check`.
- The rules are the same with every `_ui()` stripped: specs, shapes, laws, `validate`, `offered`, checks, durations and act parsing.
- Every default, written back as a declaration, is accepted and reads back equal.
- Renaming every combat skill gives the same layout and presentation.
- No skill name is spelt in the rules' interface code. Vocabulary words and the grammar's `goto` and `signal` are excepted.
- A ratchet fails when a game client file names a skill it did not name before. `CLIENT_NAMES_TODAY` lists today's matches; steps 2–4 shrink it.
- A floor overlay may restyle a base declaration.
- Compile cost with a declaration for each of the island's 62 skills: about +13% in a debug build (129 ms against 114 ms).

**Step 2 (ui-1 step 4): the skill bar, as the first user.** Step 4 (cluster and skill bar, sheathe and draw, rebindable keys, number keys and Q E R) is built on step 1, not beside it:
- **Placement:** the cluster places skills by `bar_places`. `Roles::of` is deleted from `combat.rs`.
- **The primitives:** `bar` and `slot` are shared kit primitives (`ui/kit.rs` or a new `ui/prim.rs`), not the local `bar()`/`slot()` in `cluster.rs`. The person window, the list and the extra row reuse them.
- **Looks:** `combat::look()` becomes a theme table keyed by look name. Its match on `strike`, `firebolt` and the rest goes.
- **Shipped declarations:** the seven shipped bar skills get `_ui()` declarations, with Q block, E heal and R fire bolt.
- **Sheathe and draw:** `weapon.rs` stays the local holder of `drawn`, as in example 1, until the Spark's drawn state lands.
- **Evidence:** `verify-ui` contact sheets on the island and on Cullet, and an A/B with `LIVING_GAME_PERF=ui` (section 7).

**Step 3 (ui-1 step 5): settings and rebinding.**
- Settings › Controls lists the bar places with their declared `label`s. `SkillNames` (`ui/settings.rs:88-95`) is replaced by a read of `UiSpec`.
- Gestures become `Act::Skill` bindings to declared skills, with `wave_ui` and the others each giving a `key`. `game/src/town.rs`'s `MY_ACTS` and its copied reaches go; reach comes from the spec.
- The window chips' fixed letters (`ui/win.rs:79-86`, `ui/top.rs:111-130`) read the bindings.

**Step 4: acts, the person window and the pack.**
- **Acts:** icons from `look.icon`, not `ui/verbs.rs:167-181`; groups from the spec's `want` args, labelled by `label`.
- **The person window:** its buttons are the `pin`ned person acts.
- **Drag:** uses `drag` and `drop_target`.
- **Item icons:** from the item's `icon` trait, falling back to today's substring guess.
- **Amounts:** `pick_qty` arrives.
- **Outcomes:** if the Spark adds a structured outcome, the note stops parsing English.

**Step 5: speech, after `speech-1` merges.** The chips come from `<way>_speech()` and `_ui()`, which replaces `talk.rs`'s `MODES`. The box sends `human_speak`, and kinds are drawn by `rows`. Whisper arrives with speech-2 with no client change beyond its look names.

**Step 6: meters, statuses and the workplace grid.** These depend on the Spark (`status_of`) and the dev-box (item icons, the lit and fuel facts).

**Later, only if needed:** a `ui_card` table (section 7), if the client is to stop compiling the script.

**So nothing is written twice:**
- ui-1 step 4 (Step 2) builds the bar primitives once, from `UiSpec` with defaults, and ui-1 step 5 (Step 3) reads the same `UiSpec`.
- No per-skill Rust is added anywhere: a skill name appears in Rust only inside a test.
- The WIP's `Roles::of` and `cluster.rs`'s local `bar()`/`slot()` are moved, not copied.

## 7. Costs and risks

### Frame time

- **Declarations are read once per install,** in the compile the client already does when the `script` row's revision changes. They are not re-read per frame.
- **Per frame, the UI reads Rust structs,** as it does now. New script calls are event-driven, never per frame:
  - the F hint's checks stay at 4 a second, within a 1 ms budget (`verbs.rs:56`);
  - a `grey` slot's `_check` runs when needs, knows, cost or cooldown change;
  - `detail` runs once per list opened;
  - `status_of` runs when a vitals row changes.
- **Node count must not grow.** The bar spawns once per install and updates in place.
- **The ui-1 figures.** `LIVING_GAME_PERF=ui` times the UI's own work: input, widgets and layout. Taking each run's best 10-s window under heavy load, the figures are:
  - 1.1–1.8 ms per frame with 639 nodes and nothing open;
  - 1.4–2.0 ms with two windows open (992 nodes; one run reached 4.2 ms).

  Repeats of one binary varied sevenfold on that machine (GAME_BRIEF, on the `ui-1` branch).
- **The gate for step 2** is an A/B against its base commit in the same session (same scratch world, interleaved runs, best 10-s window each). Its UI time must be no worse than the base's, and its node count, with nothing open, no higher.

### What the client reads from the world

- **First steps.** The script row grows by its declarations: about 70 names at about 150 bytes each is 10 kB on 133 kB (about 144 kB as Cullet composes it), within the 256 KiB source limit (`script.rs:824`).
- **When it is sent.** The row goes once per connect or reconnect, and again on each install. Installs are rare (`authority/src/lib.rs:128`).

### A world with a bad declaration

- **At install:** compiling the script names the function and lists the accepted keys. `validate()` then refuses unknown names, inconsistent maps and a `detail` that does not return text (section 3). The world keeps its previous script.
- **In the client:**
  - An unknown key or look name (an older client, or a newer world) falls back to its default and logs one warning, through `ui_errors`.
  - The rules are never emptied over presentation.
  - A look name with no asset in the active theme draws the theme's "empty" icon and the aim's default clip.
- **Overflow:** more skills than bar places go to the skills window, never off-screen.

### SpacetimeDB documentation check

**Read 2026-11-11:**
- [docs](https://spacetimedb.com/docs/)
- [tables](https://spacetimedb.com/docs/tables/)
- [performance](https://spacetimedb.com/docs/tables/performance/)
- [indexes](https://spacetimedb.com/docs/tables/indexes/)
- [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/)
- [views](https://spacetimedb.com/docs/functions/views/)
- [event tables](https://spacetimedb.com/docs/tables/event-tables/)
- [column types](https://spacetimedb.com/docs/tables/column-types/)
- [default values](https://spacetimedb.com/docs/tables/default-values/)
- [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/)

The pages are labelled 2.0.0. The project pins 2.14.1 (`living/Cargo.toml:10-11`, server image `living/deploy/compose.yml:6`), so the version-specific claims below were checked in the 2.14.1 crate and server source.

**This design adds no table or view in steps 1–5.** What the reading implies:
- **The script row is already the cheapest path.**
  - In 2.14.1, a query several clients share is evaluated and encoded once per change, then cloned to each subscriber (`crates/core/src/subscription/module_subscription_manager.rs:1447`, from source, not the docs).
  - Each connect still receives the whole row once. Re-subscribing to an identical query on the same connection costs nothing extra ([subscriptions](https://spacetimedb.com/docs/clients/subscriptions/)).
- **A per-player UI view would be the wrong tool in 2.14.1.**
  - Views re-run in full inside the writing transaction, a range scan makes the whole table the read set, and query views are not incremental in this version, though the docs say they can be ([views](https://spacetimedb.com/docs/functions/views/); `docs/PERCEPTION.md:36-38`).
  - A view joining cards, vitals and pack would re-run on every settle of needs. Per-player state stays in the existing point-lookup views (`my_vitals`, `my_inventory`, `my_readiness`).
- **Event tables cannot hold declarations.** Their rows are not kept, so a late joiner never sees them, and views cannot read them ([event tables](https://spacetimedb.com/docs/tables/event-tables/)). They fit only transient notices.
- **RLS is not enforced in 2.14.1** (`spacetimedb-2.14.1/src/lib.rs:108`). Anything private goes through views or reducers.

**If a `ui_card` table is ever wanted** (the client stops compiling the script):
- **Shape:** `ui_card { #[primary_key] name: String, kind: String (skill | way | meter | item), place: String, order: i32, label: String, icon: String, decl: String }`. `decl` is the whole `UiSpec` as JSON.
- **Why JSON:** automatic migration only adds columns at the end with a `#[default]`. It never changes a type, renames or reorders ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/)). Typed columns would freeze the vocabulary. `skill_card` shows a related constraint: it stores `needs` as a comma string because a column added to a live table needs a constant default (`tables.rs:1014-1016`).
- **Rows and frequency:**
  - about 60–100 rows of 200–400 bytes, so 12–40 kB;
  - rewritten only at install. In 2.14.1 an `update` with an identical row is dropped by the datastore, so unchanged rows send nothing, whether the reducer compares first, as `act_card` does (`authority/src/town.rs:126-133`), or not, as `skill_card` does (`authority/src/combat.rs:599-604`).
- **Subscribers:** every game client, whole (`SELECT * FROM ui_card`), polled like the other cards or read through `on_update`, which needs the primary key (SDK `table.rs:163-176`).
- **Indexes:** none beyond the key.
- **Cost:** this would replace the 133 kB script row, but only once the F list's `_check` no longer runs in the client. That is a separate decision.

**Data the declarations need, owned elsewhere.** These are the Spark coordinator's to design and to put through the same documentation check; this design only states the need.
- **`my_offers`:** incoming offers for a player, so step 4 can show them.
  - A per-sender view over `trade_offer` by its addressee, which needs a new `#[index(btree)] to` (today only `from` is indexed, `tables.rs:895-907`).
  - A few rows per player at most, written per offer and expiring after 3 minutes (`trade_window_s`). Its subscriber is the addressee.
  - Whether a btree equality filter counts as a point read in 2.14.1 should be measured, as `PERCEPTION.md` does for the existing views.
- **A structured act outcome:** ok or refused, and the skill, as columns added at the end with defaults on `experience`, read through `my_experience`. Written once per act end, it adds a few bytes per row.
- **A cause kind on `my_characters`.**
- **The drawn state,** on the projection and on `fighter`.
- **Possibly `my_senses`,** so the client stops re-running `senses()` with partial facts.

### What was agreed

Answers of 2026-11-11, collected in `.local/living/ui-designs/INTERFACE-answers.md` (git-ignored).

**With the Spark coordinator** (the rules and the script). All agreed; owners settled.
1. **`UiSpec` from `<name>_ui()`.** Agreed: the laptop writes it in `ui-decl-1` and the Spark reviews.
   - Condition: rules code never reads `UiSpec`.
   - A test is required: a world's rules behave identically with every `_ui()` removed. It is `the_rules_are_the_same_without_any_declaration` in `rules/src/ui/tests.rs`.
2. **The drawn state.** The Spark builds it.
   - `draw` and `sheathe` are ordinary skills that set a body state.
   - Combat specs declare a `stance`, enforced in the shared use path for players and minds.
   - The state is shown in `perceived_of` and on `fighter`.
   - Until then the client keeps a stand-in that only restricts.
3. **One `offered()` filter.** Agreed. It is shared code in `living_rules`, written in `ui-decl-1`. The Spark adds equality cases to verify-player and verify-minds.
4. **Structured outcomes.** Not as `experience` columns: `line_seen` embeds the type, so migration refuses them.
   - Instead, a private `act_outcome` table keyed by experience id (ok or refused, skill, reason code), written in the same transaction and read through `my_act_outcomes`.
   - The death cause takes the same approach. The Spark builds both.
   - Built on branch `rules-senses-outcomes`: `act_outcome`, read through `my_act_outcomes`, with act codes and death codes (`living_rules::outcome`) ([perception, "Act outcomes"](PERCEPTION.md#act-outcomes-eighth-change)).
5. **`meters()` and `status_of`.** One script law with one set of thresholds, feeding the minds' body words and alarms as well as the client. The Spark builds it. Built on branch `rules-senses-outcomes` ([world rules, "The body: meters and statuses"](WORLD_RULES.md#the-body-meters-and-statuses)): the alarms, the mind's body words and the rethink gate's levels read it; meters rows name `my_vitals` fields, so a world adds a vital with a column and a row.
6. **Whisper.** speech-1 builds `whisper_speech()` and `whisper_check` in the script.
   - The refusal wording stays in the script, not in Rust.
   - The client runs `whisper_check` before sending.
7. **Clients keep compiling the script.** `ui_card` remains a documented fallback only.
8. **`my_senses`.** A small private per-character row, updated only when a sense value changes, read through a point-lookup caller view; not a computed view. The Spark builds it. Built on branch `rules-senses-outcomes`: `character_senses`, read through `my_senses` ([perception, "My senses"](PERCEPTION.md#my-senses-eighth-change)).
9. **`my_offers`.** A btree index on `trade_offer.to` and a caller-scoped view of offers to my character. The Spark builds it first, because of the trade-offer defect.

The Spark's build order: `my_offers`, the teach fix, `my_senses`, `act_outcome`, `meters`, then the drawn state.

**With the dev-box coordinator** (Cullet's goods and recipes; rules side by the goods-2 worker).
1. **Item traits.** Every item gets `icon` (a short stable id the client maps to an image), `label` and `group`, in the shipped script and in Cullet's goods. The icon ids will be listed in [world rules](WORLD_RULES.md).
   - Their groups (food, fuel, material, tool, glass, money…) go beyond step 1's `ITEM_GROUPS`. That list is append-only, so goods-2's names are added at its end when they land, and an install refuses any other name until then.
2. **Recipe looks.** A recipe takes `icon` and `label` from its product item by default, and may override either.
   - Folding `craft`, `cook` and `smoke` into `recipes()` changes every world's rules. It is raised with the general coordinator; goods-2 is not doing it.
3. **Showing work.** goods-2 adds `make_shows()` and `feed_shows()`.
4. **Lit and fuel.** The client computes them, with no new field:
   - lit is `lit_until_ms > now`;
   - hours left is `(lit_until_ms − now) / hour_ms`, where `hour_ms = world.day_ms / 24`;
   - fuel units left is hours left × `burns.rate`.
5. **`teach_check` refusing glassmaking** is a bug. goods-2 fixes it (against `know_how()`), together with `know_how_law()`'s hard-coded list.

**Defects:**
- **Teaching:** `teach_check` refusing fire_bolt and wound_tending is the Spark's to fix, with a verify-core case.
- **`make`:** never offered at a fuel-burning workplace, probably because the client fakes facts. `my_senses` and `offered()` remove that cause, and the Spark also checks the rules side.

## References

- [Living core](LIVING_CORE.md), [communication](COMMUNICATION.md) (and §13 on `speech-1`), [perception](PERCEPTION.md), [combat](COMBAT.md), [world rules: goods, recipes and fuel](WORLD_RULES.md), [Cullet rules](CULLET_RULES.md), [game brief: verbs and Interface D](GAME_BRIEF.md).
- The owner's interface decision: `.local/living/ui-designs/DECISION.md` (git-ignored). Play-test feedback: `.local/living/playtest-{2,3,4}/FEEDBACK.md`.
- Branches read: `speech-1` (`c0aa35db`), `ui-1` (`92e667c5`), `ui-1-step4-wip` (`31b95bc7`).
