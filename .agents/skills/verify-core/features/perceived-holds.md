# Holds, as perceived (`perceived_holds_on`)

Perception parity phase 1 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the `Filter.holds` row; the audit lives on branch `perception-parity-audit`). The world law `perceived_holds_on` (an ordinary law, off as shipped) decides what a character knows a store (a storage or any kind `like` one, remains, a trap) holds:

- a graph's `{"nearest": {"kind": …, "holds": item}}` (`brain.rs`, the structure branch of `nearest`), in a target, `sees` or `near`;
- a mind's scene (`perceive::scene_json`, each store's `contents`).

**Off (as shipped):** the store's true contents, whatever the distance (the leak: a resident 10 m off knows an unseen store is empty).

**On (`stores.rs`, the new private table `seen_store`):** remembered stores. A look is the sight of a store's inside from beside it (within `stores::LOOK_M`, 2.5 m; take and store reach 1.5 m); it writes the character's own row (what was in it, and when). Looks are taken at a mind's noticing, at a player's character's perception sweep, and whenever a graph asks `holds` of a store beside it: the same rule for every controller. Then `holds` reads:

- beside the store: what is in it now;
- remembered with the item: yes (a trip there corrects a stale belief);
- remembered without it: no, for `stores::STALE_MS` (10 min) after the look; older, worth another look (yes);
- never looked into: worth a look (yes), as `can` assumes what another holds under `perceived_can_on`.

A mind's scene shows a store's contents beyond 2.5 m only as remembered (`contents` and `contents_seen`, its day clock), or `"contents": "not looked into"`. A player reads its own rows through `my_seen_stores` (identity-scoped, empty with the law off; verify-client's own-rows check). The game client does not show them yet.

**Why remembered stores, not a contents perception of open stores:** nothing marks a store as open on the map, a player's screen shows no store's inside at any distance, and a look from beside it is what a player does. A per-sweep perception of every store in sight would have to write or send rows for every store each look (a battle's remains are hundreds); a row per store one looked into, at most `stores::PER_ACTOR` (32) per character, oldest dropped first, gone at death, is bounded and is the evidence the character itself has.

Cost: off, one law read per `holds` filter and per look (nothing written). On, one point read on `seen_store` (`by_actor_structure`) per store a `holds` filter tests beyond 2.5 m; a look reads the structures within 2.5 m (`structures_near`, a chunk read) at most once a second per character and writes only on a change or every `REFRESH_MS` (60 s). `det::trace` hashes `seen_store` only once it has rows, so a trace with the law off is main's.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_holds --run "$R" > ".local/living/verify/$R/perceived_holds.txt" 2>&1
```

`scenes.py perceived_holds` (any seed, about 4 minutes): W stands 4 m from H's storage S, the only storage within 30 m; W's probe asks `sees nearest storage holds meat` (a walk 3 m north for yes, south for no). Law off: no while S is empty, yes once H stores meat (the leak). Law on: yes with and without meat while W has never looked inside, and no `seen_store` row; W brought beside S (empty) gets a row, then from 4 m no; H's refill while W stands off: still no (law off: yes); beside S again: 3 meat in the row, and from 4 m yes.

Evidence: `perceived_holds-probe-*.json`, `perceived_holds-seen-*.json`, `perceived_holds-store-*.json`, `perceived_holds-cast.json`, `perceived_holds-line.json`.

## Gotchas

- A body is not second-guessed for 45 s after it arrives; the scene sleeps until then.
- The probe reads a 3 m walk from `activity` (as `perceived_can`).
- Beside S the scene waits for W's noticing to look (up to 15 s), not a fixed time.
- `STALE_MS` (10 min) is not driven by the scene.
- A trap's catch is reckoned lazily when it is acted on (`common::trap_catch`); a look does not reckon it, so a trap looked into shows what it held when last reckoned.
- The scene restores `perceived_holds_on` in a `finally`.
