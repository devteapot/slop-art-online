# Dealings: agreements, demands and regard on records

The world's rules define social state on the engine's records (docs/WORLD_RULES.md). Agreements (`offer_terms` → `accept`), demands (`demand`) and community regard are content in `living/scripts/skills.rhai`. The primitives are the engine's: record effects, `a.records`, the `on_<skill>` / `on_expire` / `on_death` hooks, `tell` and `witness`, and stance records.

## Sub-features

- **Terms make a record.** `offer_terms` makes an `agreement` record (`offered`), and the other side is told the terms (an experience of kind `record`).
- **Acceptance.** `accept` toward the proposer makes it `agreed`, due at the first dusk at least `agreement_min_h` (12) hours away, told as "by dusk today" or "by dusk tomorrow"; the proposer is told, and onlookers see it. Cargo checks both cases (accepted at 7:00: 13 h, today; at 14:00: 30 h, tomorrow).
- **Deliveries count.** A store into the proposer's store, or a give to the other side, is counted by the `on_store` and `on_give` hooks. When one side's part is done, the other is told what it owes. When both are done, the agreement is `kept` and both are told.
- **Due:**
  - delivered by one side only: `broken` by the other, and each side is told in its own terms;
  - by neither: `lapsed`;
  - terms never accepted: the proposer hears they were not taken up.
- **Demands.** The target is told and onlookers see it. A give pays it (`met`, the demander told). Unpaid when it falls due, it is `unpaid` and both are told. A second demand of the same person while one stands is refused (Cargo).
- **Bounds.** Closed records are dropped after their keep time.
- **Regard.** The island seed's 13 regard records exist. A relation filter (`"relation": "rival town"`) picks the Kettlebridge resident by Brackenford's stance toward Kettlebridge, with no personal relation.
- **Install checks (Cargo):** a hook may not move goods; a skill with rules needs a spec; `record_text` reads every sample record.

## How to get to it

- Engine: `living/authority/src/records.rs`. Context fields: `act.rs` `skill_ctx`. Post-skill hook: `act.rs` `complete`. Death hook: `act::die`. Due records: `tick.rs` housekeeping. Stance in relation filters: `brain.rs` `relation_ok`.
- Rules side: `living/rules/src/records.rs`, `script.rs` (`hook`, `record_text`, the new effects), `script/check.rs` (`hooks`, `records`).

## Driving it

```bash
K=$R-dealings
mkdir -p ".local/living/verify/$K"
python3 "$V" launch --run "$K" --seed island > ".local/living/verify/$K/launch.txt" 2>&1
python3 "$C/scenes.py" dealings --run "$K" > ".local/living/verify/$K/dealings.txt" 2>&1
python3 "$V" cleanup --run "$K" > ".local/living/verify/$K/cleanup.txt" 2>&1
```

About 2–3 minutes. The scene installs the tree's rules with four short hours composed over them, as a floor's overlay would: `due_by_dark` 1, `proposal_h` 1.5, `demand_h` 1, `kept_h` 2. It reinstalls the tree's script at the end. The walkers are `spawn_crowd` people driven by admin `mind_act`, as a mind would decide. Snapshots: `dealings-kept.json`, `dealings-after.json` and `dealings-regard.json` (records); `dealings-regard-wave.json` (`skill_use`).

Cargo: `agreements_and_demands_are_rules_on_records` (the whole content on fixed contexts), `a_stance_is_a_holder_toward_record_with_a_label`, `terms_are_small_maps_of_plain_values`.

## Gotchas

- Walkers have no community or home: deliveries into a store count by the store's `owner`. The household match (`target.home`) is covered by Cargo, not the scene.
- Regard needs the island seed: a default-seed world has no seeded records, and the regard checks fail there.
- Players and minds are other surfaces: verify-player `deal.py` and verify-minds `dealings`.
