# Attention budget: who a character keeps track of (design note, v2)

Status: **design only, v2 with v2.1 amendments**, 2026-11-22. v2 was written on branch `attention-budget-v2` (Spark) from `origin/main` `a6375a70`; the v2.1 amendments below are on `attention-exp`, beside the selector they describe. v1 is in history at `a6375a70` (merged from `attention-budget` `112a42bf`). Nothing is built: no law, table, reducer, view, prompt or default changes, and no experiment has run.

**Why v2.** The owner answered v1 on 2026-11-22:
- on "always in": "can we make this selective? the mind decides who to track, not hardcoded";
- on the 4 chosen places: "can we make this dynamic so that it can scale with rules/skills so that we can have stats and skills changing how much a mind can keep track";
- on salience: "maybe a salience system could work/be helpful, but still that should be up to the mind";
- "so this scales well as a general system";
- "let's run different experiments in parallel and make informed decisions".

The general coordinator turned that into three changes:
1. **No hard-coded slot classes.** Attention is a policy the mind writes and the authority runs fast.
2. **Capacity is a Rhai law** over stats, skills and state, clamped by a world performance ceiling.
3. **Salience is information, not an order.**

Plus an experiments section with stop rules. What v1 established is kept: the crowd, promotion with a told reason, the memory consequences, the cost model and the hidden 14-nearest cap in minds' scenes.

## v2.1: amendments after dev-box's answers (2026-11-22)

dev-box answered §12 from main's code (`docs/ATTENTION_BUDGET_DEVBOX_ANSWERS.md` on `attention-budget-devbox` `8a9f8d6a2`). The general coordinator accepted points 1–5 and 7 as written and narrowed point 6. **Where this section and the text below differ, this section holds.** The selector on `attention-exp` (`living/rules/src/heed.rs`) implements it.

**Names.** "attention" already names the gaze band (`authority/src/attention.rs`, `human_gaze`) and the cues (docs/ATTENTION.md); "crowd" names the `crowd_sweep_n` and `crowd_frame_max_ms` laws. In code and from here on:

| This note's v2 word | Name in code |
|---|---|
| attention, attend, attended | **heed**, heeded (`living_rules::heed`) |
| attention policy, `"attend"` reply field | heed policy, `"heed"` field |
| attention instinct (`attend_person`, …) | heed instinct, `heed_person`, … in `living/seeds/heed.json` |
| `attention_capacity(a)`, its knack | `heed_capacity(a)`, `heed_knack()` (`watch`) |
| `attend_on`, `attend_ceiling` | `heed_on`, `heed_ceiling`; and `heed_contact_s`, `heed_closing_s` (new, below) |
| `attend_policy`, `attend_pick`, `attend_effect` | `heed_policy`, `heed_pick`, `heed_effect` |
| conditions `attended_s`, `acting_on_attended` | `heeded_s`, `acting_on_heeded` |
| the crowd, `seen_crowd`, the scene's `crowds` | the **throng**, `seen_throng`, the scene's `throngs` |
| `human_attend`, `mind_attend` | `human_heed`, `mind_heed` |

**1. Forced individuals: contact, not anticipation** (the general coordinator's version of dev-box's point 6). Two kinds of creature are individuals whatever the policy and outside the capacity:
- **(i) whoever the character is acting on.** Mechanical: one cannot strike a throng figure.
- **(ii) whoever made contact with it in the last `heed_contact_s` seconds** (a value-only world law, 4 s in the shipped script): a blow of theirs that landed on it, or that it blocked or dodged. Being struck is a percept the body delivers, like today's `attacked` line. After contact one knows who hit one, if they are in sight; if not, it is "struck from somewhere you could not see", as the missile rule already says.

**Not forced:** "winding up at me" and "closing on me". Anticipation is the policy's, through the instinct, which puts them first. A mind that dropped them, or an untrained one with full places, can genuinely be ambushed or flanked: the first blow lands from someone it wasn't tracking, and then the attacker becomes an individual. That is what makes capacity and the `watch` skill matter, and what E4's "blows from unheeded attackers" measures: first blows, not repeated invisible ones. So there are no invisible repeated blows, and "the mind decides" holds for everything before contact. This replaces v1's engaged overflow and §1's "no overflow" row. The instinct (§2.4) drops its `acted_on` rule, now forced.

**2. Hysteresis is seed content.** A rule may carry `"hold_s"`: what it took stays for that long after the rule last took it on its own merit, unless a better rule needs the place. The engine provides only the mechanism (`Held`, `Pick::held`); the instinct sets 5 s on its threat, speaker, watch-for and family rules and 3 s on "who is close" and the score rule. This replaces §2.3's engine-wide `attend_hold_ms`. E3(a) measures the instinct with and without its holds (docs/ATTENTION_E3.md).

**3. Only players have a perceived set** (dev-box point 1). `perceived`, `projected` and the copies exist only for players (`perception::sweep`, `combat::humans`). AI characters and every rule check call the sight rule afresh through `perception::Sensing`.
- **Players:** the heeded set can replace `far_cap`'s trim at the same point in `sweep_one`, and every copy, tier, cue and frame follows from it. A sight set kept beside the scene in module memory (`Viewer.sight`) serves earshot, the heard-row exclusion and keep margins.
- **Minds (E4's authority side):** a new heeded set in module memory, keyed by actor. Every `Sensing` reader that should see individuals consults it: graph `Sees`, `Count` (individuals and throng), `Doing`, `Threatened`, the `Nearest`/`Id` targets, cues and first sights, and `scene_json`.
- **Writers that call `in_sight` directly** must name throng members as throng: speech hearers, fight folds, witness percepts, the combat feed, the fast lane.
- The selector takes a per-character field of candidates and returns the heeded set, whichever caller asks.

**4. Throng members stay anonymous on every path** (dev-box points 3–5).
- The combat feed masks actor and target by sight only today; it must mask a throng member too. So must `my_earshot` and the experience lines.
- **Earshot keeps reading SIGHT, not heed.** `show_earshot` tells a player who hears them, and under-reporting it is a speech-consent problem.
- **A mind's on-stage detection** (`mind/src/mind.rs`) must count a player in its throng as present, so the level of detail and the rethink gate do not take it off stage.
- Throngs stay in their own `throngs` array in a mind's scene, never among `creatures` without an id, so recall builds no `person:null` key.

**5. The cost table is an extrapolation** (dev-box point 2). The per-pair cost is not constant: about 2 µs a tick at about 58 in sight, 10.6 µs at about 166 (docs/COMBAT_PHASE.md, Part A). §6's table applies one i to C = 60 and C = 200 alike, and is extrapolated from one density pending E2. dev-box proposes a `far_cap` sweep (0, 48, 32, 16, 8) that would measure the near and far marginal costs and their dependence on C.

**7. Steadier salience (after dev-box's E2).** E2 ran the v2 instinct at ceiling 16 without holds for 216 viewers: 612 flip-backs within 2 s per viewer-minute, touching 59% of heeded creatures, and 13.4 promotions per viewer-second. dev-box traced most of it to boundary oscillation from noisy features. Two changes in the selector (`heed.rs`):
- **Closing speed is smoothed.** `ClosingTracker` measures the distance change over a window, the value-only law `heed_closing_s` (1 s in the shipped script), instead of between two consecutive passes. The caller keeps one tracker per observer, observes each creature in sight at each pass and puts the answer in `Candidate.closing`; an event between passes reads its last value. A window of 0 is the old two-pass speed.
- **The incumbent wins an exact tie** within a rule (the sort key is the rule's order, then incumbent first, then distance, then id). It is mechanism, not policy: it only settles ties the policy left open, so equal scores do not flip at every pass as fighters move. A strictly better score still displaces the incumbent.

On the Cullet battle recording (docs/ATTENTION_E3.md §8) without holds, smoothing cut flicker from 222 to 169 a subject-minute (−24%) and promotions from 3.2 to 2.7 a second. The instinct's holds remain what keeps the throng still (3.4 a minute with them).

**8. What dev-box's E2 measured** (`docs/ATTENTION_E2_COST.md`, branch `attention-e2-doc`, coming to main; prototype on `attention-e2`, never merged):
- **Holds work live.** With `heed.rs` (`aa3d4d9e2`) and its holds, at 216 viewers and a ceiling of 16, a viewer sees 7–8 flip-backs within 2 s per minute (6% of heeded creatures), against 378 without holds and 612 for a reading of the v2 instinct without any grace.
- **The combat feed must be filtered by heed, not by sight.** Unfiltered, it was 128,711 rows in one 16-viewer run, naming actors and targets the viewer does not heed. That is a cost and a throng-identity leak (§4 of this list already requires throng anonymity on every path).
- **Re-ranking:** re-rank only the target, on aim and on contact. Everything else happens at the 5 Hz sweep, because `frame::moved` fires for nearly every fighter every tick (Q10). This narrows §2.3's "evaluate the policy on events, in the tick" to those two events.
- **§6's cost formula is missing a per-viewer constant.** With nobody heeded, a viewer costs 4.3–5.0 ms/s (dev-box's host), against a budget of about 1.06 ms/s at 216 viewers (600 ms/s for the tick less that host's 371 ms/s with no viewers). **No ceiling, not even 0, fits 216 viewers at 60 Hz on its own.** §6's table and its "a ceiling of 12–16 fits" do not hold.
  - **Heed still earns its place:** it halves a viewer's per-second cost at 16 viewers (11.1 → 6.5–7.3 ms/s at a ceiling of 16), lifts the saturated 216-viewer tick rate from 16.5 to 21–27, gives one perception rule for players and minds, and makes cost grow with who is heeded rather than with everyone in sight.
  - **It is not the battle-scale answer on its own.** The per-viewer floor, most of it hearing, views, the frames of unchanged scenes and the combat feed, has to come down too (E2 §4).
  - The per-heeded cost is not one constant either: about 190 µs/s each for the first 8 (the near, fighting ones), about 60–70 after; 67 ± 22 marginal across ceilings 8–32.

**6. `human_heed` shape** (dev-box point 7; SpacetimeDB docs read 2026-11-22: [reducers](https://spacetimedb.com/docs/functions/reducers/), [reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context), [column types](https://spacetimedb.com/docs/tables/column-types), all version 2.0.0; tuples are not among the listed types and `spacetimedb-sats` 2.14.1 implements no `SpacetimeType` for them, per dev-box's source reading):

```rust
#[derive(SpacetimeType)]
pub struct HeedInput { pub pins: Vec<u32>, pub focus: u32 /* 0: none */ }
#[spacetimedb::reducer]
pub fn human_heed(ctx: &ReducerContext, input: HeedInput) -> Result<(), String>
```

- No character argument: the caller's own character comes from `ctx.sender()`, like the other `human_*` reducers.
- **Hover stays on the client** (a predicted highlight). Only pin and focus changes are sent, batched by the client: one call per change, at most one every 250 ms. Each call spends an input token (`input_hz` / `input_burst`), so alternating reducers cannot raise a client's input rate.
- The authority derives a player's target from its own aimed acts, `use_skill` targets and the talk addressee, without a call.
- A click on a throng figure is a `focus` on the nearest throng member at that point, through `pick.rs`.

## 0. In short

- **One law for everyone:** each character perceives at most its **capacity** of others as individuals. Everyone else in sight is a **crowd**: scene lines for a mind, crowd rows per 6 m cell for a player (§5).
- **Who fills the places is the character's attention policy.**
  - **What it is:** a ranked list of rules in the behaviour graph's own condition words (`threatened`, `doing`/`phase`, `who` by id, kind, relation or community, `near`, `count`) and salience features.
  - **Who writes it:** the mind writes and rewrites it, like any graph.
  - **Who runs it:** the authority, on every tick that brings an event (a windup, a blow, a line, someone coming into sight), and in full at the sweep. Threats never wait on a slow mind.
  - **No row for a species' instinct:** a character without its own policy uses its species' **attention instinct**.
- **The starting attention instinct** (seed content, §2.4), for a person:
  1. whoever is going for me;
  2. whoever speaks to me;
  3. whoever I am dealing with;
  4. whoever my cues or my own choices name;
  5. family and my community nearby;
  6. up to 6 nearest within 8 m;
  7. then whoever stands out, by salience weights the policy states.

  A mind may rewrite all of it, including dropping attackers. It can then be ambushed: an emergent consequence, to watch in trials, not a bug.
- **Players** get the same instinct, edited by their own input (target, focus, pins; a settings surface later). Never by a model.
- **Capacity** is `attention_capacity(a)`, a Rhai law, the same for players and minds. It is clamped to `attend_ceiling`, a value-only law set from the cost measurements.
  - **The starting formula** (seed content, §3.2): a person starts at 10, a wolf at 8, a deer at 6. It is scaled by life stage and by knack × practice at a new `watch` skill (up to ×1.6 with practice), +4 for the technique `keeping_watch`, and narrowed by tiredness, wounds and lost breath.
  - **Range:** an untrained adult keeps track of 10, a practised watcher of 16–20 (clamped to the ceiling), a badly hurt and exhausted one of 3–4.
- **Storage:** one new private table, `attend_policy`: one row per character whose mind wrote a policy (pk `actor`, the rules as validated JSON, revision, source). Plus `attend_pick`: the controller's explicit picks (player pins and focus, Jev picks), at most 8 per character. Crowds use the public RLS table `seen_crowd` (v1). No new column on any existing table.
- **Cost:** v1's model with capacity in place of N, and the policy's own evaluation added (about 1 µs per creature in sight a second).
  - **The ceiling:** at C ≈ 200 in sight, once the planned per-individual work lands, a ceiling of **12–16** fits the 1.4–1.7 ms/s per viewer; 24 does not.
  - **Variable capacity helps:** with the starting formula most people sit at 10, below the ceiling.
  - **Provisional ceiling: 16.** It is set by E2's measured per-individual cost.
- **Experiments** (§8), in parallel:
  - **E1** (laptop): the stills;
  - **E2** (dev-box): the real per-individual cost and its answers to §12;
  - **E3** (Spark): who to track, on recorded battle and town scenes: the instinct alone, free; a mind-written policy, paid and small; Jev attention, paid and small;
  - **E4** (Spark): capacity 4, 8, 16 and 32 in arenas on the fake model, free.

  E3's paid cap is $12 in all, read from journal spend. Its stop rules are written in §8.3, before any paid call.

## 1. What changed from v1

| v1 | v2 |
|---|---|
| Fixed slot classes: (a) engaged, addressing and near "always in"; (b) 4 chosen places; (c) salience | One ranked **attention policy** per character, written by its mind. The **attention instinct** reproduces (a)–(c) as a starting point only |
| N, one world number (16) | **Capacity**, a Rhai law over the character's stats, skills and state, clamped by a world **ceiling** |
| Salience ranked (c) | Salience **features** are conditions a policy may use and weight. Only the instinct uses them by default |
| Engaged overflow past N, bounded at 8 | No overflow: capacity is the bound. A character swarmed past its capacity loses track of some attackers. E4 measures what that does |
| Jev fills (b) | Jev is one possible **author or refresher** of the policy, beside the slow mind (§11) |

## 2. The rule: an attention policy, run by the authority

### 2.1 Two grains of perception (unchanged)

Sight decides who is in sight, unchanged for every path (docs/PERCEPTION.md, "Minds see what their character sees"). Attention decides the grain:

| Grain | Who | What is perceived |
|---|---|---|
| **Individual** | the attended, at most the character's capacity | everything perceived today: the projection (name or label, band, look), motion, what they are visibly doing and at whom, speech as speech |
| **Crowd** | everyone else in sight | per area: count, where, spread, which way it moves, how many fighting or fallen, the kinds present. No identity, health, name or exact pose |

The master switch is the world law `attend_on` (off by default). Off, everything in sight is individual, as today, and minds' scenes keep their hidden 14-nearest cap ([`perceive.rs`](../living/authority/src/perceive.rs) `scene_json`). With it on, the scene lists the attended instead, the same set a player's character gets.

### 2.2 The policy: ranked rules in the condition grammar

A policy is a list of at most **12 rules**, read in order. Each rule takes the creatures in sight that match its condition, in its order, up to its `take`, into the places left. Filling stops at the capacity. A creature already taken is not taken again.

```json
{"attend": [
  {"if": <condition about the one considered>, "order": "nearest", "take": 3, "why": "<own words>"},
  {"score": [{"if": <condition>, "w": 2.0}, ...], "take": "rest", "why": "<own words>"}
]}
```

- **`if` rules** take the matches, ordered by `order`. The orders are `nearest`, `closing` (fastest toward me), `newest` (in sight the shortest time) and `longest` (attended longest, which keeps a hold).
- **`score` rules** sum the weights of the conditions each creature meets, and take the highest first, nearer first on ties. This is where salience lives: **as weights a policy chooses**, not as an engine ranking.
- **`take`** is a count or `"rest"`. The default is all matches.
- **`why`** is up to 160 characters in the mind's words. It is quoted when the rule promotes someone out of a crowd (§5.3), as a cue's `why` is (docs/ATTENTION.md).

**Conditions about the one considered.** These are the graph's own words, scoped to the creature being considered instead of "anyone in sight". Each reads only what the character's perception already holds.

| Condition | Meaning | The graph's word it reuses |
|---|---|---|
| `{"who": 412}`, `{"who": "wolf"}`, `{"who": {"kind": "person", "relation": "family"}}` | by id (one already met, as cues require), kind, or relation: `friend`, `enemy`, `stranger`, `family`, `community` | `Filter` (`graph.rs`), plus `community` |
| `{"threatened": true}` | this one's attack or throw is winding up at me, or they are threatening me | `Threatened` |
| `{"doing": {"is": "hostile", "phase": "winding up", "at_me": true}}` | what they visibly do, its phase, whether at me | `DoingCond`, without `who` |
| `{"attacker": {"within_s": 10}}` | hurt me within the last N seconds | `Attacker`, `HurtWithin` |
| `{"addressing": {"within_s": 10}}` | spoke, waved or offered to me | `Speaker`, `Hailer`, the scene's "asked of you" |
| `{"acted_on": true}` | the target of my own act now | my `fighter`/`doing` target |
| `{"near": 8}` | within N metres | `Near` |
| `{"cued": true}` | matches one of my cues (docs/ATTENTION.md) | cue matching |
| `{"chosen": true}` | named in my `attend_pick` rows: a player's pin or focus, or a Jev pick | new (§4) |
| `{"attended_s": {"above": 2}}` | already attended this long | new |
| `{"self": <any graph condition>}` | a gate on my own state: `{"self": {"health": {"below": 50}}}` | every self `Cond` (`Health`, `Energy`, `Night`, …) |
| `all`, `any`, `not` | combinators | `All`, `Any`, `Not` |

**Salience features** are conditions too. Nothing ranks by them unless a policy says so.

| Feature | Meaning |
|---|---|
| `{"closing": {"above": 1.0}}` | approaching me at over N m/s (the rules' target context already has `closing`) |
| `{"fighting": true}` | visibly in a fight move |
| `{"fallen": true}` | down or dead |
| `{"acting_on_attended": true}` | their visible act is aimed at someone I attend |
| `{"new": 5}` | in sight for under N seconds |
| `{"loud": true}` | heard calling, shouting or crying within the hearing law's reach |
| `{"lit": true}` | carrying a light at night |

`count` is a gate on the crowd around me, not on the one considered: `{"self": {"count": {"of": "person", "within": 10, "at_least": 20}}}`. It counts the attended and the crowd, because a crowd's numbers are perceived.

**What the policy cannot do.**
- **It cannot see more than sight.** Every condition is read over creatures in sight. A person under the far label ("someone too far away to make out") matches no id and no relation, as cues do.
- **It cannot exceed capacity.**
- **It cannot act.** It selects whom the character perceives individually and nothing else.

### 2.3 How fast it runs

The authority runs the policy itself; no model is asked.

- **On events, in the tick.** The frames already mark what changed (`frame::moved`, `fought`, `did`, `hurt`) and the engagement set (`frame::engaged_of`, extended to every character with the law on). When one of those events involves a creature in a character's sight, the authority evaluates the policy for that one creature and that character, in the same tick. Events are: a windup or release, a blow, a line or gesture, an offer, coming into sight.
  - If the creature ranks above the lowest attended one, it takes that place.
  - With the instinct, an archer winding up at me from 20 m is attended in the tick its aim is seen, as v1's (a) and today's near tier do.
  - The cost is one rule pass per event pair, not per crowd.
- **In full at the sweep.** The whole policy re-ranks everyone in sight at the character's perception cadence: a player's sweep (200 ms), an AI's evaluation slot (1 Hz, plus wakes and the fight cadence). Crowd members are ranked at the crowd's 1 Hz.
  - Each creature's features are computed once per pass (distance, closing, kind, relation bit, visibly-doing).
  - Rules then test those features; no Rhai runs per creature (docs/CAMERA.md, "Proposed cadence").
- **Hold.** A creature attended for under `attend_hold_ms` (1,000) keeps its place against lower-ranked ones; a higher-ranked one still displaces it. A policy can say more with `attended_s` and `order: "longest"`.
- **The same code everywhere.** The policy's parser, validator and selector live in the shared rules crate (`living_rules::attention`, pure functions over a candidate list), like the graph's conditions. The authority and E3's replay tool both call it, so the experiments test the code that would run and not a second simulator (AGENTS.md).

### 2.4 The starting attention instinct (seed content)

Instincts are only starting graphs. The attention instinct is a starting policy per species, in `living/seeds/instincts.json` beside the behaviour instincts, as keys `attend_person`, `attend_wolf` and `attend_deer`. A world may change it. A character with no `attend_policy` row runs its species' instinct (§4).

**Person** (players and minds alike):

```json
{"attend": [
  {"if": {"any": [{"threatened": true}, {"doing": {"is": "hostile", "at_me": true}}, {"attacker": {"within_s": 10}}]},
   "order": "nearest", "why": "whoever is going for me"},
  {"if": {"addressing": {"within_s": 10}}, "order": "newest", "take": 2, "why": "whoever speaks to me"},
  {"if": {"acted_on": true}, "why": "whoever I am dealing with"},
  {"if": {"any": [{"cued": true}, {"chosen": true}]}, "order": "nearest", "take": 4, "why": "whoever I watch for"},
  {"if": {"all": [{"who": {"kind": "person", "relation": "family"}}, {"near": 20}]}, "order": "nearest", "take": 2, "why": "my own people"},
  {"if": {"near": 8}, "order": "nearest", "take": 6, "why": "who is close"},
  {"score": [{"if": {"closing": {"above": 1.0}}, "w": 3}, {"if": {"acting_on_attended": true}, "w": 3},
             {"if": {"fighting": true}, "w": 2}, {"if": {"who": "wolf"}, "w": 2},
             {"if": {"new": 5}, "w": 1}, {"if": {"loud": true}, "w": 1}],
   "take": "rest", "why": "whatever stands out"}
]}
```

**Wolf:**
1. whoever is going for me;
2. my pack, `{"who": {"kind": "wolf", "relation": "family"}}`, up to 3;
3. prey or quarry in sight, `{"who": "deer"}` or my `acted_on`, nearest, up to 3;
4. the nearest within 8 m;
5. then a score on `closing` and `fighting`.

**Deer:**
1. any wolf in sight, nearest first;
2. whoever is going for me;
3. my herd within 8 m;
4. then a score on `closing` and `new`.

Every number is seed data. These policies reproduce v1's (a), (b) and (c) for a person, which makes E3's free arm comparable with v1. The prompt's examples (§2.5) are placeholders, never these lines.

### 2.5 Who edits the policy

| Controller | How it edits | Through |
|---|---|---|
| **A mind** | An optional `"attend"` field in its think and consolidate replies: the full ranked list, replacing the character's policy; `"attend": []` returns it to its instinct. The prompt gains `# What you keep track of`: each rule in the mind's words, how often it took someone in the last minutes, and what it missed (blows from someone it was not keeping track of, told truthfully as such). | `mind_update` gains `attend: Option<AttendIn>` (`None` leaves it), as cues are projected. The mind service validates first; the authority validates again and keeps a refusal with its reason, which the next prompt lists |
| **Jev** (§11) | Never writes rules. It refreshes `attend_pick` rows, read by the policy's `chosen`. Or it picks which of the mind's saved policies is active. | `mind_attend` (picks), `mind_attend_use` (switch) |
| **A player** | The instinct reads the player's own input through `chosen` (focus, pins, a held hover, a click on a crowd figure). A settings surface that edits the rules themselves is a later client change. | `human_attend` (v1 §3.5, question 9); later `human_attend_policy`, the same validation |

**The reply grammar** (`prompts.rs`, beside `notice_field`):
- one line saying the field exists and replaces the list, with the condition words and orders;
- three placeholder examples: a kind, an id with a deed, a score with two features.

A unit test, as `cue_examples_name_no_one`, fails if the examples name a stranger, an attacker, a guard, a duty or a role, or teach a tactic.

**Validation** (`living_rules::attention::parse`, `deny_unknown_fields`). A policy is refused whole, with the reason kept, when it has:
- more than 12 rules, or more than 4,096 bytes of JSON;
- an unknown condition, kind, phase or order;
- an id the character has never met (no `familiar`, `relation` or known name; `cue_refusal`'s rule);
- a `take` of 0;
- a `why` over 160 characters;
- a `score` with no weights, or a weight outside −10..10.

A refused policy leaves the previous one in force. A policy with no rule that can take a threat is accepted: whether to watch attackers is the mind's choice.

**Played characters keep no mind-written policy**, as they keep no cues (docs/ATTENTION.md, "Who keeps cues"). Their policy is the instinct plus their input.

### 2.6 What attention changes elsewhere (both controllers)

As v1 §1.4, with "the attended" now whatever the policy and capacity give.

| Path | With the law on |
|---|---|
| A player's copies (`seen_body_copy`, `seen_character_copy`, `seen_fighter_copy`, doing, cues) | the attended only. Crowd members are counted in crowd rows |
| A mind's scene (`scene_json`) | the attended, each as today, plus crowd lines (§5.1) |
| Behaviour graphs (`sees`, `nearest`, targets, `threatened`, `doing`) | individuals: the attended. Counts: the attended and the crowd. A graph that reacts to `threatened` reacts only to threats from the attended, so a policy that drops attackers leaves the graph blind to them |
| Aimed acts by id | the target must be attended. A player clicking a crowd figure promotes it first, if a `chosen` rule leaves room |
| Witnessed events, fight folds, first sights | named per attended creature. Crowd members' deeds fold into crowd lines. `familiar` rows and first sights only for the attended |
| Hearing | a line addressed to me makes its speaker `addressing`, which the instinct ranks second. Other crowd speech is heard as "someone in the crowd to the east says …" |
| Cues | matched against everyone in sight. A match makes the creature `cued`, which the instinct ranks fourth |

## 3. Capacity: a Rhai law

### 3.1 The law

`attention_capacity(a)` lives in `skills.rhai` (seed overlays may replace it, as Cullet's `laws.rhai` replaces `senses`). It returns how many others the character keeps track of now. The engine clamps the result to `[0, attend_ceiling]`.

- **The same law for players and minds.** It reads only the character's own facts, through the actor context the skill laws already use (`living_rules::script::context::ACTOR`): `kind`, `stage`, `hp`, `vitality`, `energy`, `stamina`, `knows` and `factor`.
- **Two additions:**
  - `factor` for a named knack: the declaration says which skill's knack × practice the law reads.
  - `attend_bonus`: a sum of active temporary effects (§3.4).
- **Its declaration**, like `senses_law()`:

  ```rhai
  fn attention_capacity_law() {
      #{ cadence: "event", topic: "attention", knack: "watch",
         about: `How many others one keeps track of at once as individuals (everyone else in sight is a crowd): ${attention_about()}` }
  }
  ```

  `cadence: "event"` means the engine re-runs it for a character only when an input it reads changes band. The engine knows which fields the law reads (`Reads`), so a wound re-runs it and a step does not. It caches the answer by the inputs' value, as the regard law is cached (docs/PERCEPTION.md, "What an observer perceives of a target"). A world has a handful of distinct inputs, so the law runs rarely.
- **The character knows its own capacity.** "You can keep track of about 10 people at once; you are tired" goes into `my_senses` for a player and into `you` in a mind's scene. It is a fact of one's own body, as `senses` is.

### 3.2 The starting formula (seed content)

```rhai
// How many others a creature keeps track of as individuals; everyone else in sight is a crowd
// (docs/ATTENTION_BUDGET.md). Seed content: a world may change every number. The engine clamps
// the answer to the world's `attend_ceiling`.
fn attention_capacity(a) {
    let c = switch a.actor.kind { "person" => 10.0, "wolf" => 8.0, "deer" => 6.0, _ => 6.0 };
    c *= switch a.actor.stage { "infant" => 0.3, "child" => 0.7, "elder" => 0.9, _ => 1.0 };
    // Watchfulness: inborn knack × practice at keeping watch (the `watch` skill): about 1.0
    // untrained, up to 1.6 with long practice (genes::practice_factor).
    c *= a.actor.factor;
    // A technique one can learn or be taught.
    if knows(a, "keeping_watch") { c += 4.0; }
    // Tiredness and pain narrow attention; so does being out of breath.
    if a.actor.energy < 15.0 { c *= 0.6; } else if a.actor.energy < 35.0 { c *= 0.8; }
    let health = a.actor.hp / (max_hp(a.actor.kind) * a.actor.vitality);
    if health < 0.25 { c *= 0.6; } else if health < 0.5 { c *= 0.8; }
    if a.actor.stamina < 10.0 { c *= 0.85; }
    // Effects that sharpen or dull attention for a while (§3.4).
    c += a.actor.attend_bonus;
    max(1.0, floor(c))
}
```

| Character | Capacity before the ceiling |
|---|---|
| Untrained adult, rested, unhurt | 10 |
| Adult with long practice at `watch` (factor 1.6) | 16 |
| … who also knows `keeping_watch` | 20 (clamped to the ceiling, 16 provisional) |
| Untrained adult, badly hurt (below 25%) and exhausted | 3 |
| … also out of breath | 3 (10 × 0.6 × 0.6 × 0.85 = 3.06) |
| Child | 7 |
| Wolf / deer, unhurt | 8 / 6 |

**The `watch` skill** (seed content, new): "keep watch: stand and look about for a while" (4 s, no target).
- **Practice:** using it practises it, as any skilled skill (`common::practise`).
- **Knack:** every founder gets a `knack:watch` gene, as for every skill with a knack (`genes.rs`).
- **Its effect:** a short `attend_bonus` while it lasts (+2 for 20 s) and faster sweeps of the crowd. It is the in-world way to "look around", the same for players (the skill bar) and minds (a deliberate act or a graph leaf).

**`keeping_watch`** is know-how like any technique: taught, learned from a tablet, or found by experiment (docs/LIVING_CORE.md, know-how).

### 3.3 The ceiling

`attend_ceiling` is a value-only world law (the Delivery class, live-tunable by `law_override`, docs/LAW_OVERRIDE.md). It is not seed content: it is set from measured cost (§6), not from taste.
- **Provisional value: 16.** E2 measures the per-individual cost, and the ceiling follows from §6's formula.
- **It caps every character equally.** A world can lower it under load without touching anyone's formula.
- **The clamp is visible.** The character's own words say "you could keep track of more, but no more than 16 here" only if the world's law text says so. By default the clamp is silent and `law_about` describes it.

### 3.4 What rules and skills can do with it

- **Practice:** `watch`'s factor grows with use; future skills can add their own knack, through the declaration's `knack`.
- **Know-how:** a technique adds places.
- **Effects:** a skill's `_done` effects may return `#{ op: "attend", add: 2.0, secs: 20.0 }`. That is a new effect op writing a timed `attend_effect` row (§4), summed into `attend_bonus`. "A rally cry", "a strong brew" or "a blinding flash" (negative) are seed skills a world may add.
- **State:** any actor field the context exposes. Exposing temperament (`trait:caution`) to laws is a separate context change, not proposed here.

## 4. Storage and tables

Per AGENTS.md: new tables, never new columns (in 2.14.1 appending a column rewrites the table and disconnects every client; docs/BATTLE_VIEWERS.md Addendum 1). The authority's working state lives in module memory, backed by these rows.

| Table | Columns, indexes | Written | Read | Retained, growth |
|---|---|---|---|---|
| **`attend_policy`** (new, private) | `actor` u32 pk; `rules` String (the validated JSON, ≤ 4,096 B); `revision` u32; `source` (`mind`, `player`); `refused` String (the last refusal's reason, empty if none); `updated_ms` | `mind_update` with `attend`, `human_attend_policy` (later) | by pk, once per revision: the parsed policy is cached in module memory by `(actor, revision)`, as graphs are | one row per character that has its own policy (none for instinct-only characters); deleted at death (`act::die`), as cues are |
| **`attend_pick`** (new, private; v1's `attend_choice`) | `id` u64 pk auto-inc; `actor` u32 btree; `target` u32; `source` (`pin`, `focus`, `hover`, `click`, `jev`); `weight` f32; `until_ms` u64 | `human_attend` (rate-limited, one change per 250 ms), `mind_attend` (Jev) | by `actor` at the sweep or slot, for `chosen` | ≤ 8 a character; expired rows deleted once a second by an `until_ms` range, as `reveal` is |
| **`attend_effect`** (new, private) | `id` pk auto-inc; `actor` btree; `add` f32; `until_ms` | a skill's `attend` effect | by `actor` when capacity is re-run | ≤ a few a character; expired rows deleted as above |
| **`seen_crowd`** (new, public, RLS `viewer = :sender`) | v1 §2.2: pk `key(viewer, cell)`, `viewer` btree, cell, count, centroid, spread, heading, moving, fighting, fallen, kinds | the crowd pass, 1 Hz, changed cells only | by the one viewer's subscription | ≤ 48 × viewers; about 0.5 MB/s of commitlog at 216 viewers (v1 §3.4) |
| Module memory | `ATTENDING` (attended set, hold times), `CAPACITY` (by actor, with its inputs' key), parsed policies | the selector | the frames, the scene, graphs, folds | none: a fresh instance re-derives from the rows and the instincts at the next pass. Places may reshuffle once, never wrongly, since the rows are the source |

- **No view, and nothing new for the mind service to subscribe.** The mind sees its own policy's effect through the scene and `# What you keep track of`, which the service builds from rows it already reads plus `attend_policy`. That is a private table, readable by the owner identity the service uses.
- **The Jev state** is the v1 procedure `mind_attention_state(actor)`. It is returned to the controller only and writes nothing, like `mind_reach`.
- **Migration:** adding tables is an automatic migration with no disconnect (docs/ATTENTION.md, citing [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/)). `seen_crowd`'s RLS rule disconnects every client once at publish (v1 §3.4).

**SpacetimeDB documentation** (read 2026-11-22 for v1; every page shows version 2.0.0; the pins are 2.14.1):
- [Row-level security](https://spacetimedb.com/docs/how-to/rls): experimental and unstable; `:sender` is bound to the caller; the owner bypasses it. `seen_crowd` takes the copy tables' safeguards.
- [Views](https://spacetimedb.com/docs/functions/views/): per-user views cost one computation per subscriber. No view is added.
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): never cached by clients, yet logged. Crowd rows are state a reconnect needs, so they are a regular table.
- [Performance](https://spacetimedb.com/docs/tables/performance/): indexed lookups, small focused tables, private where clients need nothing. Every new read is by pk or `actor`.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/): B-tree point and range lookups.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): initial rows, then deltas.

## 5. The crowd and promotion (kept from v1)

### 5.1 To a mind

Scene lines per direction and distance band, built from the same cells as the player's rows. Counts are rounded; there are no ids.

```json
"crowds": [{"dir": "northeast", "dist": "a stone's throw", "about": 40, "across": "about 20 m",
            "moving": "toward you", "visibly": "most fighting; 3 fallen", "kinds": "people"}]
```

### 5.2 To a player

One `seen_crowd` row per 6 m world-aligned cell (at most 48, the farthest merging 2×2), drawn by the client as generic, non-interactive figures placed by centroid and spread (v1 §2.2).

### 5.3 Promotion: a place and a told reason

A crowd member becomes an individual only when a rule of the character's policy takes it.
- **A mind:** told in its own labels, quoting the rule's `why`: "You pick out a stranger in the crowd to the north (whoever stands out)". For threats, the windup or blow is itself the told event.
- **A player:** sees a short reason marker from the rule (`going for you`, `your pin`, `your people`, `close`).
- **Demotion** is silent, as leaving sight is.

## 6. Delivery cost with a variable capacity

v1 §3 is kept, with capacity c in place of N and the policy's evaluation added to the crowd's per-creature cost. Per viewer and second, with C in sight and K crowd cells:

**cost ≈ c × (i + 10 µs) + (C − c) × 3 µs + K × 5 µs**

| Term | v1 | v2 |
|---|---|---|
| per attended creature: delivery i + sight at 5 Hz | i + 10 µs/s | unchanged |
| per crowd member | 2 µs/s (sight at 1 Hz) | **3 µs/s**: sight, plus its features and the rules at 1 Hz (about 1 µs: 12 rules on a precomputed feature row) |
| per crowd row | 5 µs/s (assumed) | unchanged |
| events | – | one rule pass per event pair in the tick; a few per creature a second in a fight; within the per-attended term |

**Per viewer (ms/s), against a budget of 1.4–1.7:**

| c | C ≈ 200, K = 48, i today (120) | C ≈ 200, K = 48, i planned (30–40) | C ≈ 60, K ≈ 15, i today | C ≈ 60, K ≈ 15, i planned |
|---|---|---|---|---|
| off (everyone) | 26 | 8–10 | 7.8 | 2.4–3.0 |
| 8 | 1.9 | 1.1–1.2 | 1.3 | 0.6 |
| **10** (untrained adult) | 2.1 | **1.2–1.3** | 1.5 | 0.6–0.7 |
| 12 | 2.4 | 1.3–1.4 | 1.8 | 0.7–0.8 |
| **16** (provisional ceiling) | 2.9 | **1.4–1.6** | 2.3 | 0.9–1.0 |
| 24 | 3.9 | 1.7–2.0 | 3.3 | 1.1–1.4 |
| 32 | 4.9 | 2.0–2.3 | 4.3 | 1.4–1.8 |

- **The ceiling bounds the worst case; the formula sets the typical case.** A battle of untrained adults sits at 10, where the dense case fits with margin once i is down. A ceiling of 16 fits the dense case only at the top of the budget. 24 does not fit.
- **Before the planned per-individual work, only c ≤ 8 fits (10 at the top of the budget), and only at the battle's edge.** Attention is necessary but not sufficient (v1 §3.2).
- **The ceiling from E2:** `attend_ceiling ≈ floor((1.5 ms/s − (C − c) × 3 µs − K × 5 µs) / (i + 10 µs))` at the contract's dense case.
- **AI characters pay too.** 200 fighters running their policies over 200 in sight, at 1 Hz plus events, cost about 200 × 200 × 1 µs ≈ 40 ms/s of the tick. Against that, the fight fold's naming falls from 43–51 ms/s (it names only the attended; docs/BATTLE_SCALE.md, Fix 4), and minds' scenes list fewer creatures. Net about zero, to be measured in E2 and E4.

Evidence for C and K (v1 §3.3, `attention_density.py` on the act trial's 200-mind battle): others within 48 m p50 57, p90 169; crowd cells at 6 m beyond 16 attended p50 24, p90 50.

## 7. Minds' prompts and memory

Kept from v1 §4, with one change: what a mind learns depends on its own policy.
- **They learn only the individuals they attended to,** plus crowd facts. Attention narrows perception and never adds to it, so "minds know only what they perceive" holds. Now the narrowing is the mind's own choice within its capacity.
- **The policy is evaluated over what is in sight.** Every feature it reads (a windup aimed at me, a kind, a relation, closeness) is perceptible. The selection is perception run by the law, as recognition was in v1.
- **The policy is itself memory.** It lives in the mind's store with the concepts it serves, as cues do. `rules` is a projection, and an `attend` reply replaces it. Consolidation may keep, change or drop it; the reorganizer sees `# What you keep track of` like any other line of the mind.
- **Prompt cost.** A scene lists up to the capacity: about 10 at the starting formula (today's cap is 14), 16 at the ceiling (+2 × 85 tokens on a 4,700-token battle think prompt). `# What you keep track of` adds about 100–300 tokens when a mind has its own policy, and nothing on the instinct (the prompt names it in one line).
- **The hidden 14-nearest cap is removed** with the law on. The prompt, the graph and memory agree on one attended set, the same for a player's character.

**Emergent consequences.** All are from the same law for everyone; none is scripted.
- **Ambush.** A mind that rewrote its policy without attackers, or one swarmed past its capacity, does not see some windups. Its graph's `threatened` stays false, and the blow lands.
- **Crowds as cover, and searching:** as v1 §4.
- **Distraction:** a policy weighted to `fighting` follows the loud fight and loses the quiet one.
- **Character shows in attention.** A cautious mind that keeps 4 places for "anyone closing on me" survives ambushes and misses its friends' signals. A sociable one keeps its people and misses the stranger. Both are choices the mind wrote and can revise from what it lived ("I was struck from behind by someone I was not watching").
- **Skill matters.** A practised watcher keeps track of 16, an untrained one 10, a wounded and exhausted one 3. A wounded fighter loses track of the fight, which may spiral (lower capacity, more unseen blows). E4 watches for that.

## 8. Experiments

Four experiments run in parallel on three machines. Each answers one question, and none depends on another's result to start. E3's free part and E4 need a small build first (§8.4).

| | Machine | Question | Cost |
|---|---|---|---|
| **E1** | laptop | Does a 200-fighter battle still read as a battle with c individuals and an impostor crowd? Stills at c = 16 and 32 against everyone-individual, as v1 §5.1 specified (`far_cap` = c as the individuals' mock, 6 m cells, Middle, Far and inside) | free |
| **E2** | dev-box | The real per-individual cost i (near and far), the crowd row cost k, the answers to §12, and from them `attend_ceiling` (§6's formula). A fake-model battle at 216 and 16 viewers, as v1 §5.2, with capacity fixed at 10, 16 and 24 through the ceiling | free |
| **E3** | Spark | Who to track: does a mind-written policy or Jev track what the mind later acts on better than the starting instinct, without missing more threats? | free part; paid part ≤ $12 |
| **E4** | Spark | Does capacity matter in a fight: do low-capacity characters miss more, get flanked more, fight worse? | free (fake model) |

### 8.1 E3: who to track, on recorded scenes

**Inputs** (copied out of `~/slop-evidence` to a scratch directory first, with sha256 recorded; never read in place):
- **Battle:** the act trial's 200-real-mind battle, both arms (`act-trial-20261121.tar.zst`: `minds-atb1-off-055246`, `minds-atb1-on-060222`). It has 1 Hz body samples with movement segments (so positions replay to any moment), skill uses with accepted and outcome times, act attempts, and every real think and compile prompt and reply.
- **Town:** the same trial's town arms (40 real minds, 30 minutes; `samples.jsonl`, `side/activities.jsonl.gz`, journals).
- **Arena:** the pack arena's trial folders (5 Hz bodies, uses; docs/PACK_MIND.md §5), for flanking scenes.

**States.** A frozen random sample of decision moments, drawn before anything runs and hashed:
- 200 battle states (100 per battle arm);
- 100 town states, at moments with at least 8 creatures in sight, so the choice matters.

Each state is a subject at the moment of one of its recorded think requests. Its field is rebuilt from the samples through the rules crate:
- positions along segments;
- sight from the run's world laws (range, field, light);
- the map regenerated from the run's seed. If the seed's map does not regenerate identically on this toolchain, cover is ignored and the report says so.

Each state is followed for **30 s**, re-run every second with the arm's policy fixed.

**Arms** (the same states for every arm; capacity from the starting formula with the subject's recorded health, and a second pass at fixed 8 and 16):

| Arm | Policy | Cost |
|---|---|---|
| (a) instinct | the starting attention instinct (§2.4), alone | free |
| (b) mind-written | one call per state on the subject's own route (the `people` mix's think model, DeepSeek V4.1 Flash): its saved think prompt as it was (its memory, cues, stances and the scene it saw), plus the `attend` reply field (§2.5) and nothing else. Run once per scene: the policy is fixed for the 30 s | paid: about 300 calls |
| (c) Jev | the instinct, with `chosen` filled by Jev (§11): one TypeSafe `systemone` request per state at its start and every 6 s (5 per state), each with the state's own field and questions from the subject's own cues, relations and concerns. Replay rate only, concurrency ≤ 4 | paid: about 1,500 calls |

**Measures** (per arm, per scene type, per state, paired across arms):

| Measure | Definition |
|---|---|
| **M1 threats missed** | landed blows on the subject within the window whose striker was not attended when the windup started, per 100 landed blows. Also windups aimed at the subject that start unattended, per minute |
| **M2 acted-on share** | of the creatures the subject later acted on within the window, the share attended when the act was decided (the compile reply's time) and when it started. Acted on means named in an act attempt, the target of a skill use, spoken to, or the target its graph resolved. Also reported for acted-on creatures beyond the 8 nearest, where the arms can differ |
| **M3 churn** | promotions and demotions per minute; mean hold time |
| **M4 cost** | tokens, latency and $ per state, from the journals |
| **M5 validity** | (b): the share of replies that parse into a valid policy, and the refusal reasons; (c): the share of Jev replies used |
| **Blind check** | 60 states, two fresh Claude subagents, blind to arm: for each arm's attended set, is it a plausible set for this character, given its ties and concerns? |

- **Known bias.** The recorded minds decided with full perception (their prompts listed the 14 nearest). M2 therefore favours distance-like policies, so (a) has an advantage. The beyond-8-nearest share is the fairer comparison.
- **M1 is counterfactual.** Who would have been attended; the recorded blows happened under full perception.

**Decision rules** (frozen with the states):
- **(b) or (c) is preferred over (a)** if its M2 beyond the 8 nearest is higher by at least 5 points (paired by state, exact sign test p < 0.05), its M1 is no worse by more than 1 per 100 landed blows, and its M3 is at most 1.5× (a)'s.
- **(c) over (b)** by the same rules.
- **Otherwise the simpler arm stands:** (a) before (b) before (c).
- **The report states which held, per scene type,** with every failed state kept.

### 8.2 E4: capacity in arenas (fake model, free)

**Fixtures**, on the trial stack's scratch worlds through `trials.py`, with the subjects' minds on the fake model, so their attention policy is the instinct and only capacity varies:
1. **The pack arena** (docs/PACK_MIND.md §5): people subjects against a wolf pack, by day and at night. Its measures come from `pack_arena.py`: M2 flanking (coverage, encircled share, rear-blow share), M5 casualties, M6 duration.
2. **A two-sided melee:** 60 people in 2 sides (`spawn_battle_sides`), no refills, until one side breaks.

**Arms.** The subjects' capacity is fixed at **4, 8, 16 and 32** by a seed laws overlay that replaces `attention_capacity(a)` for people only. The wolves and the other side keep the starting formula. There is also an arm with the starting formula itself. `attend_ceiling` is 32 in all arms.

**Replicates.** 6 per arm and fixture, interleaved, each with its own world.

**Measures:**
- blows landing from unattended attackers, per subject-minute;
- rear-blow and encircled shares;
- blocks or dodges per windup aimed at a subject;
- the subjects' own blows landed;
- deaths and health lost by side;
- engagement duration;
- churn;
- the share of each subject's time at capacity, and its capacity over time (the wound spiral: does capacity fall faster than health?);
- an indicative tick cost of the selector per arm (not a measurement series: it runs under the trial-activity lock, not `battle.lock`).

**Decision rule** (`pack_arena.py`'s §5.5 rule): an arm differs from the capacity-16 arm on a measure when its median lies outside the 16-arm's range and at least 2/3 of its replicates do. The question is answered "yes" if capacity 4 and 8 differ in the direction of more unattended blows, more rear blows and more subject deaths. The results tune the seed numbers of §3.2, and they tell the owner what a ceiling of 12 or 16 costs in play.

**Stop rules (free):**
- a quiet start (load below 8, or redo);
- each world in its own scratch database;
- a run whose world guard pauses for disk is discarded and redone, not counted;
- no change of fixture after the first replicate.

### 8.3 E3's paid part: stop rules, written before any paid call

1. **The cap: $12 for E3 in all, read from the journals' spend.**
   - Spend for (b) is priced from its tokens at the committed prices (`act_trial.py` `PRICES`, docs/MODEL_COST.md).
   - Spend for (c) is the journal's `cost_usd`, which the mind computes from the **local** prices file (`living/mind/src/prices.rs`). Jev's price is never written in this document, a report or a commit.
   - **Arm caps:** (b) $4, (c) $5. The remaining $3 is a reserve, spent only with the general coordinator's word for a rerun.
   - Each arm stops at its cap minus $0.25 (calls in flight), and everything stops at $11.50 total.
2. **The guard runs first.** An `act_trial.py watch`-style guard on each arm's own journal glob is started and confirmed to be reading entries (one fake call seen) before the first paid call. On `battle-frame`, a watcher given a directory exited at once and the replay ran unguarded for 30 s.
3. **No price, no Jev.** Without a local prices file `cost_usd` is null, the spend cannot be tracked, and (c) does not start.
4. **Failures.** An arm stops when more than 10% of its last 50 calls fail (at least 20 calls).
5. **Jev throughput is unknown.**
   - Concurrency is never above 4.
   - One HTTP 429, or a p95 latency above 1 s over the last 50 calls, pauses (c) for 5 minutes at half concurrency. A second trip stops it.
6. **(b) validity.** If more than 30% of the first 50 replies fail validation, (b) stops. The prompt is fixed on the fake model (free), and (b) resumes only with the coordinator's go. What was spent counts toward the cap.
7. **Frozen inputs.** States, prompts, question templates, models, capacities, measures and decision rules are hashed before the first paid call. Any change after that is a new run needing approval.
8. **Replays only.** No live world, no real-model mind service, no battle.
9. **Order.**
   - (a) runs first, free.
   - Then the free parts of (b) and (c): prompts only (token counts per request), the fake model through the call path, validation of fake replies.
   - Then the coordinator's go.
   - Then (b), and (c) after it, so a (b) problem cannot spend (c)'s share.

### 8.4 What must be built before E3 and E4

- **Before E3 (no authority change):** `living_rules::attention` (the grammar, the validator, the selector and the starting instincts as data), and a `living-mind attention-replay` subcommand that builds fields from saved runs and calls the selector. For (b), it sends the `attend` field through the mind's own `Llm`; for (c), the Jev request. The prompt-audit test of §2.5.
- **Before E4:** the authority side behind `attend_on` (off by default): the selector in the tick, capacity, `attend_policy` and `attend_pick`, the scene's attended list, graphs reading the attended. `seen_crowd` is not needed for E4 (no players), so its RLS publish waits for E2 and the client.

## 9. Verification plan (once built)

As v1 §5.3, with the policy's cases. Each touched surface's skill is maintained in the same change (`maintain-verification-skill`), because tables, reducers, the mind protocol and the seed format change shape.

| Surface | New or changed scenes |
|---|---|
| verify-core | `attention_policy`: the instinct's order, `take`, `score` weights, capacity reached, the hold; a custom policy without attackers misses a windup and the blow lands; `attend_on` off identical to main (`det_compare`). `attention_capacity`: the law re-run on a wound and on practice, an `attend` effect, the ceiling clamp. `attention_ambush`, `attention_fold` (v1) |
| verify-generation | the instincts' `attend_*` keys load, and a seed overlay replacing `attention_capacity` validates |
| verify-client | `crowd_tables.py` (v1): `seen_crowd` isolation; `attend_policy`, `attend_pick` and `attend_effect` refused to players and anonymous |
| verify-player | `human_attend`: only one's own character, bounds, rate limit, a pin or click becomes `chosen`; a player's character keeps no mind-written policy |
| verify-minds | `attend-reply`: a reply's `attend` validated, projected, refused with its reason listed in the next prompt; `# What you keep track of`; `attention-jev` (v1) |
| verify-llm | the Jev attention purpose journaled, `cost_usd` null without a prices file |
| verify-knowledge | crowd members never become person nodes; the policy kept and faded with its concept |
| verify-ui (laptop) | crowd figures, click to promote, the reason marker, the capacity shown with the senses |

## 10. Default and risks

**Default: off** (`attend_on` false). After E2 and E4 it goes on per world by `law_override`, a battle world first. Default-on in play is the owner's call. The starting formula and instincts are seed content, so each world may differ.

**Risks to watch in trials.**
- **Minds dropping attackers.** A rewritten policy without threat rules leaves a mind blind to windups. That is emergent and allowed; trials count it (E3 M1; live trials: blows from unattended attackers per mind-hour, and how many minds rewrote their policy without a threat rule).
- **Degenerate policies:** a policy that keeps one person only, or that churns (`newest` first in a crowd). The hold time bounds churn; trials report churn per mind.
- **The wound spiral:** hurt lowers capacity, which lowers awareness, which lets more blows through. It may make fights end faster. E4 measures it; the formula's numbers are seed data to tune.
- **Players and minds may differ in practice.** A player's instinct follows their input, a mind's is rewritten by thought. Both start equal, and trials compare blows from unattended attackers for players' characters and minds' characters.
- **Cost.** Capacity bounds the individuals, but the policy's own evaluation is per creature in sight (§6, about 3 µs/s each). If E2 measures it higher, the crowd's rule pass moves to 0.5 Hz.
- **The reversed 2026-11-10 ruling.** Crowd members get no first sights, no `familiar` rows and no named fight lines. Trials across the switch are not comparable, and every batch record states `attend_on` and the ceiling.
- **RLS is experimental:** one more RLS table, with the copy tables' safeguards and a disconnect at publish.

## 11. Jev: one possible author or refresher of the policy

Kept from v1 §7 (shape, costs, the 2026-11-09 rule), with its role narrowed. **Jev never writes rules and never chooses an act.** It can do one of two things for a mind that has it switched on:

1. **Refresh `chosen`:** the v1 shape.
   - **Request:** one `systemone` request per mind, only while more is in sight than its capacity, every 1–3 s.
   - **State:** that mind's own current field, at most about 30 creatures, from `mind_attention_state`.
   - **Questions:** from the mind's own cue texts, relations, stances and projects, plus "who here is about to matter to you?".
   - **Answers:** `choice` over handles, written as `attend_pick` rows (source `jev`, weight = probability, 5 s life). The policy reads them only if it has a `chosen` rule; the instinct does, fourth.
2. **Switch between the mind's own saved policies.**
   - A mind may keep up to 4 named policies, like routines: "in a crowd", "on watch", "with my children". Its `attend` reply names them; storage is `attend_policy` keyed `(actor, name)` instead of `actor`.
   - **Question:** one `choice` question, "which of your ways of keeping track fits what you perceive now?", picks the active one.
   - **Cost:** one question, at most every 10 s, cheaper than option 1.
   - It is untested; E3's (c) tests option 1 only.

**Load and cost** (v1 §7.5): about 2,400–2,700 input tokens a request; 20–60 calls a fighter-minute in a battle, about 0 in a town. A 200-fighter battle-hour is about 5–14 times the rethink gate's Jev use for 2,000 people for an hour. Latency p50 135–174 ms. TypeSafe's rate limits are not recorded in the repository.

Jev bills input tokens only, and its price lives only in the local prices file. The plain policy (the instinct, plus the mind's own cues and rules) is the baseline Jev must beat in E3.

**The 2026-11-09 rule holds.** Jev is not real-time: it refreshes picks every 1–3 s, or switches a policy every 10 s or more. It shapes only who is perceived as an individual, through rules the mind wrote. Threats reach a policy that watches for them in the tick, without Jev.

## 12. Questions for dev-box (E2)

v1 §3.5's nine questions stand: `perceived` as the attended set; the per-individual cost split near and far; promotion and demotion churn; crowd rows' budget; `seen_crowd`'s shape; the RLS publish window; projections for crowd members; the engagement set for AI viewers; `human_attend`'s shape. v2 adds two:

10. **Event-driven re-ranking in the tick.** The policy is re-evaluated for one (character, creature) pair when the frames mark that creature changed and it is in the character's sight. Is the frames' changed-set (`frame::moved`, `fought`, `did`, `hurt`) per tick the right hook, and is a per-pair check there affordable at 216 viewers × 200 in sight in a battle? *Assumed: yes, since only pairs with an event are checked, a few per creature a second.*
11. **Variable capacity.** Copies per viewer now vary between characters and over time (a wound lowers capacity mid-fight, dropping copies). Is there any frame-budget assumption that the scene size changes only with sight? *Assumed: no; a capacity change is a batch of demotions, like creatures leaving sight.*

## 13. Open questions

**For the owner:**
1. Accept the attention policy and capacity law in place of the 2026-11-10 "no attention cap" ruling, and retire `far_cap`?
2. The starting formula's numbers: person 10, wolf 8, deer 6; `watch` up to ×1.6; `keeping_watch` +4; tiredness and wounds ×0.6–0.8. These are seed content, to tune after E4.
3. The crowd's look and cell size, after E1.
4. Whether a player may later edit the rules themselves (a settings surface), or only pins and focus.
5. Jev's second role (switching between saved policies): explore it after E3, or not at all?

**For the general coordinator:**
1. E3's sub-caps ($4 for (b), $5 for (c), $3 reserve).
2. Whether E3's (b) should use DeepSeek V4.1 Flash (the battle's think route) or the subject's own recorded route.
3. The go for the §8.4 builds before E3 and E4 (Opus, by AGENTS.md's routing).

## Evidence

- v1 (`a6375a70`): the density, cell and scene figures (`living/tools/attention_density.py` on the act trial's battle), the Jev token figures (the gate-quality replay journals) and the cost inputs (docs/COMBAT_PHASE.md, docs/BATTLE_LAWS.md, docs/BATTLE_VIEWERS.md). No evidence was read for v2.
- Code read at `origin/main` `a6375a70`:
  - `living/rules/src/graph.rs`: `Cond`, `Filter`, `Target`, `DoingCond`;
  - `living/seeds/instincts.json`;
  - `living/authority/src/tables.rs`: `routine`, `brain`, `judged`, `cue`;
  - `living/authority/src/mind.rs`: `MindUpdate`, `mind_reach`;
  - `living/mind/src/prompts.rs`: `notice_field`;
  - `living/rules/src/script/context.rs`: `ACTOR`;
  - `living/rules/src/genes.rs`: knack and practice;
  - `living/scripts/skills.rhai`: `senses`, `senses_law`, `pools`, `appraise`, `attack_done`;
  - `living/tools/act_trial.py` (`PRICES`), `pack_arena.py`, `battle_diag.py`.
- The E3 Jev volume (about 1,500 requests at about 2,700 tokens) was checked against its $5 sub-cap with the local prices file without printing the price: it fits.
