# Seeded lives on the island

Since 2026-11-10 ([seeded lives](../../../../docs/SEEDED_LIVES.md)). The island seed's residents are authored: households, sheets, relations, the places their authors gave them, and starting ways for carriers and outlaws made of ordinary skills. Nothing in the engine knows a role. This feature checks that the world holds those facts and that instinct-only residents act on them through the existing rules.

## Sub-features

- **Seat** (right after publishing): every resident of the seed is placed with its sheet; every hamlet the seed names is peopled; every sheet relation is a `relation` row; every carrier knows the way to its far market as stages (`work 1` … `work n`, each leg 220 m or less); every outlaw has a spot on the road (`work`, `along_m` from home).
- **Routes** (watched): carriers leave home with goods (`take` at the home `store`), reach their stages and the far market's store (`work`), `store` there, take that market's surplus and walk back. Goods move between settlements' stores.
- **The road**: outlaws keep their spot by day; with a friend near, they `threaten` an outsider passing; an outsider threatened while outnumbered and with no friend near `yield`s (the island's `stay safe`); the outlaws `seize` from someone who yielded. Chronicle rows `threat`, `yield`, `seize`.
- **Ties**: gestures (`wave`, `nod`, `face`) aimed at someone, classed by the actor's seeded relation to its target (`friend`, `enemy`, `known`, `none`).

## Driving it

```bash
R=core-lives-$(date +%Y%m%d-%H%M%S)
V=.agents/skills/verify/scripts/verify.py
python3 "$V" launch --run "$R" --seed island
python3 .agents/skills/verify-core/scripts/lives.py --run "$R" --minutes 20 --every 8
python3 "$V" cleanup --run "$R"
```

`--seat-only` stops after the seat checks. The watch reads rows only: no scene, no reducer call, no player. Evidence: `lives-seat.json`, `lives-watch.json` (samples of carriers and outlaws, store goods before and after, road chronicle, gestures by relation), `lives.json` (checks).

## Gotchas

- A world day is 12 real minutes and work happens by day: watch at least 14 minutes for a carrier to finish a leg of its route, 20 for a round trip on the shorter roads.
- Whether an outlaw's threat happens depends on who passes their spot while they keep it. A watch in which no outsider passes records zero threats; that is not a failure of the rule. The check on the road requires only that the outlaws keep their spot.
- Gestures by relation are evidence, not a pass condition: they depend on who meets whom.
- Long journeys without seeded stages still fail the 6,000-expansion walk search ("no path there"): that is a rule gap (docs/SEEDED_LIVES.md), not this feature's defect.
