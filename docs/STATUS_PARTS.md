# `status_of` in per-meter parts (API sketch, not built)

*Sketch for the general coordinator, 2026-11-13. Note B in [BATTLE_SCALE.md](BATTLE_SCALE.md) (on `battle-profile`) has the profile behind it. Nothing here is built.*

## Why

At 200 fighters the body's alarms (`brain.status`) cost 29 ms/s, 12% of the tick.
- The character's alarm cell answers 411 asks a second. 298 go to the law.
- The rules' memo, keyed on every fact `status_of` reads, answers only 30 of them; 268 run the script, at about 75 µs each.
- The memo misses because one fast-moving fact changes the whole key. Stamina changed at 74% of asks, `hurt_ago_s` at 14%; health, energy and hunger rarely.

Split into parts, each kept on its own inputs, a change of stamina alone re-asks only the part that reads stamina. The estimate is 10–16 ms/s saved, to be measured.

## The script's side

A world may declare the parts of `status_of` and their order:

```rhai
// The parts of how a body is, in the order their statuses are listed. Each reads only what it
// needs; the engine keeps each part's answer on the facts it reads.
fn status_parts() { ["hunger_part", "energy_part", "health_part", "cold_part", "combat_part", "breath_part", "slowed_part", "mending_part"] }

fn hunger_part(a)  { if a.hunger == () { [] } else { [hunger_status(a.hunger)] } }
fn energy_part(a)  { if a.energy == () { [] } else { [energy_status(a.energy)] } }
fn health_part(a)  { let f = a.share.health; if f == () { [] } else { [health_status(f)] } }
fn cold_part(a)    { /* freezing: a.night, a.kind, a.hp_rate, a.hunger */ }
fn combat_part(a)  { /* in_combat: a.hurt_ago_s */ }
fn breath_part(a)  { /* out_of_breath: a.stamina */ }
fn slowed_part(a)  { /* slowed: a.kind, a.energy (slow_words) */ }
fn mending_part(a) { /* wasting or recovering: a.hp_rate, a.share.health */ }

// The reference: the parts joined, in order. It stays the law's definition; the engine checks
// that the parts give the same answer.
fn status_of(a) {
    hunger_part(a) + energy_part(a) + health_part(a) + cold_part(a) + combat_part(a) + breath_part(a) + slowed_part(a) + mending_part(a)
}
```

- **Each part** takes the same body `a` as `status_of` (facts rounded as now) and returns a list of status entries: none, one or several. The entries are `status_of`'s, with the same keys (`STATUS_KEYS`).
- **`status_parts()`** is read once when the script compiles, like the other declarations. It names unary functions of the script, each at most once.
- The parts are ordinary functions: a world splits its law as it likes. The shipped split follows the meters, because the meters change at different rates.

## The engine's side (`living_rules::script::body`)

- **At compile:**
  - read `status_parts()`;
  - work out each part's read plan with the same static field analysis `status_reads` uses (`fields.of(part, 1)`, `share.<meter>` expanded to its value and max fields);
  - a part whose reads cannot be worked out (it reads the body whole or by computed names) is kept on the whole body, as `status_of` is today.
- **At an ask** (`Scripts::status_of(&BodyFacts)`, the one entry point the authority, the mind service and the game client already use):
  - for each part in order, take its key (`BodyFacts::key_reading(part reads)`);
  - look it up in that part's memo (`KEPT` states each, cleared when full, as now);
  - on a miss, call the part with a map holding only its reads (as skill checks are given only their plan's fields), validate the entries, and keep them;
  - join the answers, so the result is the same `Rc<Vec<Status>>`.
- **`status_reads()`** becomes the union of the parts' reads. The authority's alarm cells (`brain::alarm_statuses`) and `BodyFacts::next_change_ms` are unchanged: a cell still holds the joined answer until a fact any part reads can change.
- **Counters while profiling** (`living_rules::script::calls`): parts asked, answered from memo, and run, by part.
- **The `status_parts` law** (on) uses the parts; off, `status_of` whole, as now. It is the rollback.
- **The `status_parts_check` law** (a diagnostic): at every ask that runs at least one part, also run `status_of(a)` whole, and log and count any difference (`status_parts:differed`).

## Install checks (`script/check.rs`)

A world's script is refused when:
- `status_parts` names a function the script lacks, one that is not unary, or one twice;
- a part returns something other than a list of status entries, or an entry with unknown keys;
- **the parts joined differ from `status_of`** on the sample bodies the validation already builds (each meter low, mid and full; night and day; hurt just now and long ago; each kind and stage). The refusal names the first differing body and both answers.

The last check matters for worlds composed from floors (`floors::compose`). A world that overrides `status_of` but inherits the shipped `status_parts` would otherwise have its override silently ignored. With the check, such a world must override both or neither, and is told so: "status_of and status_parts disagree: override both or neither".

## Migration

- **Worlds without `status_parts`:** no change. `status_of` is asked whole and kept on everything it reads, as today.
- **The shipped `skills.rhai`:** `status_of`'s body is split into the eight parts above, and `status_of` becomes their join. Each existing `*_status` helper stays. The statuses, their order, their words and the alarms are unchanged; the check law and the install check prove it.
- **Tables, reducers, bindings:** none change. No column, no migration of stored data.
- **Clients:** the mind service's body words and the game client's pills go through the same `Scripts::status_of`, so they get the same answers, kept the same way.
- **Docs:** the script contract's `status_of` entry (docs/WORLD_RULES.md, "Meters and statuses"; `script/body.rs` module docs) gains `status_parts` and its rule (parts joined = `status_of`).

## What it would take to build

- `living_rules::script::body`: parts, per-part plans and memos, and the joined answer.
- `script/check.rs`: the install checks.
- `skills.rhai`: the split, and the two laws with their words.
- Rules tests:
  - the shipped parts joined equal `status_of` over a grid of bodies;
  - a stamina-only change asks one part;
  - an override of `status_of` alone is refused.
- A verify-core case: fighters with `status_parts_check` on (none differ), and with `status_parts` off.
- A profile at 200 fighters for the saving.

## Decision asked

Whether to extend the script contract with `status_parts`. The general coordinator decides.
