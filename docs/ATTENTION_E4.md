# E4: does heed capacity matter in a fight?

Status: **built behind `heed_on` (off by default) and measured on the pack arena, fake model, free.** 2026-11-22, branch `heed-e4` (Spark), from `origin/attention-exp` `0aba82f2`. It is the Spark's E4 of docs/ATTENTION_BUDGET.md §8.2 (v2 with the v2.1 amendments). **Nothing merges to main until the owner decides on the law.** The 60-person two-sided melee (`spawn_battle_sides`) waits for `sides-battle-fix` on main. The player side (heed replacing `far_cap`'s trim in `sweep_one`, throng rows to clients) is not built: players keep today's perception even with the law on.

@@RESULTS@@

## 1. The authority side (behind `heed_on`)

`living/authority/src/heed.rs`. A character the authority runs (no person plays it: `combat::human` is none) perceives through heed when the world's `heed_on` law is on.

- **The set.** Per character, in module memory: the selector's picks (`living_rules::heed::select`, the code E3's replay runs), each pick's last time on merit (for its rule's `hold_s`), how long each has been heeded and in sight, and the last pass's field. The policy is the species' instinct (`living/seeds/heed.json`): no mind writes one in E4 (`mind_update` has no `heed` field).
- **The full pass** runs at most once a second per character, from its behaviour evaluation, or from any reader that finds the set missing or older than 3 s. Its candidates are built from what the body perceives (`perception::Sensing`): kind, distance, closing speed, made out or far, family by parentage (and friend, enemy, stranger, community only when the policy reads them), windups aimed at it, what it visibly does (`perception::visibly`), who hurt it and when, who spoke or waved to it, whom it acts on, contact, cue matches, heeded and in-sight times. Loud and lit are not filled (the instinct's `loud` weight is 1 and never fires; listed below).
- **The event pass** (`living_rules::heed::admit`) runs in the tick for a windup aimed at the character (`act::begin`, before the fast lane counts it), a creature coming into a full scene, a cue's match, and words to it.
- **Forced, outside the capacity, whatever the policy:** whoever the character acts on (its activity's or move's target) and whoever made contact within `heed_contact_s` (a blow that reached it: landed, blocked or dodged; `act::damage` and a dodge by evasion). Both are worked out when a reader asks, so they are never stale.
- **Capacity:** the world's `heed_capacity(a)` over the character's own facts (`act::facts`, its practice and genes), clamped by `heed_ceiling` (`Scripts::heed_capacity`), at each full pass.
- **Diagnostic law `heed_trace`** (value-only, off in play): logs, for characters with a mind, each pass (`heed pass id cap health in_sight picked forced`), each windup aimed at one (`heed windup … seen heeded contact`) and each blow that reaches one (`heed blow … first repeat_in_window seen_at_windup heeded_at_windup`). An invisible repeated blow (contact within the window before the windup, yet not an individual then) is logged as `heed invariant` whether or not tracing is on.

**Module memory and rollback.** The SpacetimeDB reducers page (read 2026-11-22, version 2.0.0, [reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior"): "Relying on global variables, static variables, or module-level state to persist across reducer calls is undefined behavior"; "SpacetimeDB may run each reducer in a fresh WASM or JS instance"; "If you modify global state and then roll back the transaction, the modified value may remain for subsequent transactions". The 2.14.1 source reading in docs/PERCEPTION.md ("Module memory and rollback") holds: one instance, a trap or publish starts a fresh one. The heed set is therefore a cache of a selection, never a record: a fresh instance has none and every reader asks for a pass; a pass or a contact a rolled-back transaction left in memory is re-derived by the next pass or lapses within `heed_contact_s`. Nothing is written to a table: no table, column, reducer, view or subscription changes, so no migration and no bindings.

### What each `Sensing` reader does under `heed_on`

| Reader | Under heed (AI characters) | Where |
| --- | --- | --- |
| graph `sees`, the `nearest`, `id`, `attacker`, `speaker`, `hailer`, `parent`, `partner`, `named` targets | individuals only (`first_seen` filters, `seen_by_id` refuses a throng member; a refused act says "no #id in sight") | `brain.rs` |
| graph `count`; the crowd alert ("among a crowd of about N") | individuals and throng: a throng's numbers are perceived | `brain.rs` |
| graph `doing` | individuals only | `brain.rs` |
| graph `threatened`; the `threatened` desire signal | only a windup by an individual (one from the throng is not seen coming); the instinct's first rule admits a windup aimed at one in the tick | `brain.rs`, `heed::windup` |
| cues | matched against everyone in sight; a throng member that matches is `cued` and takes the event pass, the cue fires only if it becomes an individual | `brain.rs` `cues` |
| first sights, `familiar` rows, "a wolf is close" | individuals only | `brain.rs` `noticed` |
| a mind's scene (`scene_json`) | the individuals in full (the hidden 14-nearest cap is gone with the law on); the rest as `throngs` lines (`dir`, `dist` band, `about` count, `across` spread, `moving` relative to one, `visibly` fighting, `kinds`), never among `creatures`; `visibly.at` and `doing → whom` name only individuals | `perceive.rs` |
| earshot in a mind's scene | **reads sight** (speech consent): throng hearers are counted, named "someone in the throng to the …" | `perceive.rs` |
| a mind's on-stage detection | a player in the throng is counted in the scene's `_stage.throng_players`; `watched` treats it as a player present; `prompts::model_scene` strips `_stage` from every prompt | `perceive.rs`, `mind/src/mind.rs`, `prompts.rs` |
| witness lines, missile lines, fight folds | a throng member is "someone in the throng to the …", subject or object 0 | `perceive.rs`, `fold.rs` |
| speech heard | a speaker in the throng: "Someone in the throng to the … says: …", subject 0, no introduction; words to the hearer are an event (`addressing`) first | `speech.rs`, `heed::addressed` |
| `mind_reach` (talk frame) | a throng member is not perceived as them | `mind.rs` |
| the fast lane's "move seen again" | a move by a throng member is not counted | `fast.rs` |
| **unchanged** | players (sweeps, copies, combat feed, `my_earshot`: no throng exists for them yet); steering's hold on a target (it is acted on, so forced); smell; heard-not-seen; the `apart` push | |

## 2. Off is the base, byte for byte

`living/tools/det_compare.py run --scripts BASE,CAND` (each copy installs its own build's shipped script; the base is `attention-exp` `0aba82f2` exported with `git archive`, built in its own target dir):

@@DET@@

## 3. E4 fixture

@@FIXTURE@@

## 4. AI tick cost

@@COST@@

## 5. Checks

@@CHECKS@@

## 6. Open questions

@@OPEN@@
