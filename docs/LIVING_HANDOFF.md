# Living core handoff (2026-09-27)

Experiments were stopped on request on 2026-09-27 at about 21:10 local time. This note says:

- what state things are in;
- what the last runs showed;
- where to pick up.

The day-by-day evidence and every rule change are in [STAGES.md](STAGES.md). The architecture is in [LIVING_CORE.md](LIVING_CORE.md).

## State

- **Labs.** Nothing is running: no lab, mind service or watcher.
  - Two worlds remain on the local SpacetimeDB (`127.0.0.1:3300`), paused with their data kept for analysis: `stage3-village` and `stage4-two`.
  - Resume one with `living/tools/lab.py <scenario>`. This publishes a *fresh* world. To continue a paused one instead, unpause it and start its mind.
  - Delete them when done: `living/tools/stdb delete -s local <db> -y`, then `living/tools/reclaim_disk.sh 0`.
- **Journals.** Model journals are under `.local/living/journal/<run>/`; those of finished runs are gzipped.
  - The last runs are `stage4-two-1790518849` and `stage3-village-1790520577`.
  - Watch reports are under `.local/living/watch/{s3-village,s4-two}/`.
- **Services.** The observer web server may still be serving at `http://127.0.0.1:8330/?db=<db>`; its lab picker lists the two labs above. Neo4j and SpacetimeDB run in Docker (`sao-living-*`).
- **Code.** Everything is committed on `living-core`. `just living-check` passes: authority, mind, native and web observer, and rules tests. `living/tools/verify_mechanics.py` passes 18 checks.

## What changed on 2026-09-27

1. **Skills say what they take and give.** Each skill's inputs and outputs are described by `skill_io` in `living/scripts/skills.rhai`, built from the same numbers the rules use. Minds read them from the live rules script. A failure caused by a missing input names where that input comes from.
2. **Rework is a skill.**
   - Minds no longer rewrite routines in their replies. They use the `rework` act, which takes time sitting still; the rules script decides when a way has been lived with enough to change.
   - Routine stats reset per version, and routine names are canonical.
   - Onlookers see a rework only as someone "sitting deep in thought".
3. **Skills can be conditions.** `{"can": {"do": ...}}` holds when the rules would let a skill start now.
4. **Model routing.** Mistral Small runs inside an adaptive in-flight window (grows while calls succeed, shrinks on HTTP 429) and overflows to Luna. The half-Luna rotation was removed.
5. **A less crowded world.**
   - Grass regrowth is a world law (`pasture_regen`), 4× lower.
   - The stage 4 realm is 320 tiles across, with towns 150 tiles apart and open towns spread with their households.
   - The observer draws every sprite in proportion at every zoom.
6. **New know-how.**
   - Techniques: fishing (nets), smoking, basketry, archery (`shoot`), tanning (leather, armor), medicine (salves), trapping (traps catch meat over time) and bridging.
   - A new `clear` skill turns forest into open ground.
   - Townsfolk start knowing where the other towns stand, through their background.
7. **Combat.** Real-time moves that a mind decides as acts become its intent (weighed above staying safe); they were refused before. The seeded "stay safe" habit faces a wolf when others are near.
8. **Storages hold 120 things.**

## What the last runs showed

Two labs ran the new code: `stage4-two`, about 5.4 hours, two towns on the 320 realm; and `stage3-village`, about 5 hours, three families in the 96-tile valley.

| | village | two towns |
|---|---|---|
| people ever / alive at stop | 28 / 16 | 38 / 20 |
| generations reached | 4 | 3 |
| human deaths | 8 old age, 2 killed by people | 9 old age, 1 killed by a person |
| speech between groups | 413 lines | 399 lines |
| gifts / trades between groups | 16 / 3 | 12 / 1 |
| all trades | 5 (berries↔fiber, wood↔fiber) | 1 (torch for wood) |
| know-how among the living | fire 9, storage 3, fishing, shelter, spear, carpentry | fire 14, storage 10, torch 5, cooking 4, spear 3, medicine 3, fishing 2, trapping, cloak, … |
| how know-how was gained | 11 taught, 1 worked out | 28 taught, 1 worked out |
| new items made | none (4 spears) | none (9 torches, 1 salve used) |
| skill uses: gather vs craft | 8,178 vs 0 | 15,415 vs 10 |
| reworks (habit changes) | 16 | 34 |
| routines using `can` | 4 | 9 |
| wildlife at stop | none | 236 deer, no wolves |

### Findings, most important first

1. **Dead characters' rows are never removed, so active tables grow without bound.** Stage 4 held 1,300 characters (about 1,200 dead deer). It kept 6,076 routines of the dead (5,868 deer), 4,197 routine stats and 2,123 practice rows. Genomes are also kept for every character. Clean up at death:
   - delete routines, routine stats and practice;
   - keep what an expected child still inherits, if anything.

   This matters directly for the 2,000-character target (see AGENTS.md on bounded retention).
2. **People learn but do not make.**
   - New techniques spread by teaching (39 taught, only 2 worked out by experimenting), but no new item was crafted in either lab.
   - Gathering is 80–95% of all skill use; stage 4 had stored 1,901 wood before the 120-item storage limit.
   - The limit fired only three times before the stop, so its effect on habits is unmeasured.
   - The seeded work habits (gather and store, forever) give activity without purpose. Next to try: work habits that make or build what the group lacks, or feedback that shows what stored goods are for.
3. **Contact and conflict emerged.**
   - Speech between groups rose from near zero (28 lines in the earlier village) to about 400 lines per lab.
   - Real exchanges happened: fiber for berries, wood for fiber, a torch for wood.
   - The first people-on-people killings have readable causes. Gale, whose family was freezing without cloaks and who distrusted the neighbours, went to take hides and fiber from Pepeba's stores; Gale killed Pepeba, then was killed by Isebrine. That is stage 4's "conflict with interpretable causes", though still single events.
4. **Ecology is unsettled in both labs.**
   - Village: people hunted all 20 deer in about 40 minutes, and the wolves then died of old age.
   - Stage 4: 5 wolves on the large map never bred, while deer boomed and starved (481 starvation deaths, 236 alive).
   - Earlier, an in-place 4× cut in grass regrowth collapsed the previous village: deer died out, the wolves turned on people, and 18 of 21 were killed.
   - Lessons:
     - Change carrying capacity only in fresh worlds.
     - Small predator populations on large maps need a way to find mates.
     - The user asked not to chase balance for its own sake, but predators and combat cannot be tested with no wolves left.
5. **Memory consolidation merges other people into oneself.** For example, `{"from": "person:11", "into": "self"}` in Garhanka's journal. Merges into `self` should be refused or at least logged. Consolidation is also a third of all calls.
6. **Model cost.** Stage 4 made 38,000 calls and used 266M tokens in 5.4 hours for about 30 people plus animals:

   | Use | Tokens | Per call |
   |---|---|---|
   | person compile | 109M | 12,000 |
   | person consolidation | 62M | 10,000 |
   | person think | 51M | 5,900 |
   | animals | 35M | — |
   | talk | 9M | — |

   - Mistral took 95% of calls with 25 rate limits in 36,500 calls; Luna took the overflow (p50 7.7 s against 3.3 s).
   - The skill reference with takes and gives adds about 2,500 characters to every compile prompt. Showing takes and gives only for skills a person can use would cut it.
7. **Combat fix is only lightly tested.** After the fix, 2 people were killed (both by people) and none by wolves, but wolves were few or gone. The earlier failure is recorded in STAGES.md: minds decided to fight, and the acts were refused.

## Where to pick up

- Bounded retention for the dead (finding 1), with a measurement of table sizes over a long run.
- Purpose and making (finding 2): rerun stage 4 with the storage limit from the start, then decide about work habits.
- Consolidation merging into `self` (finding 5).
- Stages 3–4 status:
  - Contact, first trades and first conflict are there; storage, roles and repeated exchange are not.
  - Stage 5 (several hubs, about 150 people) has not started.
  - Mind level of detail (`LIVING_LOD=1`) is opt-in and was off in these labs.
- Cleanup discipline: retire labs as soon as they are superseded (stop minds, delete the database, reclaim disk, trim the observer's `LABS`, gzip journals).
