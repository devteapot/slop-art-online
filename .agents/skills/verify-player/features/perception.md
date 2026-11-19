# What a player perceives of others

Since 2026-11-09 (docs/PERCEPTION.md, "What an observer perceives of a target"). `seen_characters` is each creature's record through the script's `perceived_of` law, for this player: its name only when known (else a label such as `a stranger`), health as a band unless a skill reveals more. `appraise` (declared in skills.rhai like any skill) reveals exact health for 20 s to whoever uses it. Saying one's own name tells it to everyone who hears.

## Sub-features

- A newcomer perceives a resident as `a stranger` (empty `name`, a `label`), health as a band (`hp` -1); `seen_characters` has no `controller`, home, parents or `ai` column.
- `human_act {"do": "appraise", "target": {"id": N}}` is carried out (`skill_use` outcome "a stranger has 100 of 100 health"), and the appraiser's `seen_characters` row for N then carries exact `hp`/`max_hp`; a bystander beside it still has `hp` -1 and a band. The appraiser's `my_experience` holds "You look a stranger over: … of … health."
- After the reveal's 20 s the appraiser sees a band again.
- The appraiser says "Hello, I am <name>." and the bystander, who heard it, perceives the appraiser by name (`name`, `label`) and its experience reads "<name> said: …".
- **A resident resting on is seen resting** (since `doing-renew`, 2026-11-19; `scripts/rest_seen.py --run "$R"`, default seed, about 1.5 min, needs the verify-client probe built). A resident under a lone rest desire rests 8 s at a time 3 m from the player, who sees it. The player's own subscription (`SELECT * FROM seen_doing`, the probe under the player's identity) for 30 s: the row arrives with the initial rows; each renewal reaches the client as one update (its end moved on within 100 ms of the old end, `since_ms` kept), with no delete and no insert. A graph that walks the resident off deletes the client's row at once (22–66 ms after the call in the runs of 2026-11-19; the authority's own row 6–106 ms). Before doing-renew each renewal was a delete and, 0.6–1 s later, an insert (`--baseline`: 586, 1023 and 1042 ms). Admin calls: `spawn_crowd`, `place_at`, `set_behavior`. Evidence: `rest-seen.json`, `rest-seen-stream.jsonl`.
- **A walking player is perceived walking** (since `fix-perceived-moving`, docs/PERCEPTION.md "Activity derived from the body"). A player walking at a resident by `human_move` is in the resident's deliberation scene as `"doing": "walk → you"` (before fix-perceived-moving: `wait`; until first-sight-crowd: `walk → person`), and the resident's first sight of it reads a walk ("…, 8 tiles east, walk → you."). Standing, it reads `wait`. An AI resident walking the same line by `goto` reads `goto → you`: whom someone goes to is named as the observer perceives them since first-sight-crowd. A bystander player's client gets the same for both: the body moving in `seen_bodies`, no `seen_doing` row (read by SQL within 1.5 s of the walk starting: a near creature's copy follows at most every 500 ms since frame-views, its changes reaching a subscribed client as cues meanwhile; docs/PERCEPTION.md "Cues and tiers").
- The game client sends the same act from its **V** key (or the script step `gesture:appraise[:ID]`), at the creature under or nearest the cursor, else the nearest within 6 m, people or animals. While the row carries `hp`, the nameplate shows and carries a small `hp / max` under its bar; when the reveal ends the readout goes ([verify-client game-client](../../verify-client/features/game-client.md)).

## How to get to it (user POV)

Two players stand by a resident. One looks the resident over (the appraise act); their health bar shows exact numbers for a while, the other player's shows only how hurt the resident looks. When one player introduces themself, the other's nameplate shows their name.

## Driving it

```bash
.agents/skills/verify-player/scripts/appraise.py --run "$R"
```

On an island run (`$V launch --run $R --seed island`; best with `LIVING_PERCEPTION=scoped`). It mints a second identity (kept as `token2`), joins both players if needed, holds a resident still with `set_behavior {"wait": 120}`, and sets the scene with `place_at` (named in the report: not something a player can do). Evidence: `appraise.json`, `actions.log`.

What others perceive of a walking player:

```bash
.agents/skills/verify-player/scripts/approach.py --run "$R"            # the fix: walk → you (the target named as R perceives it, since first-sight-crowd)
.agents/skills/verify-player/scripts/approach.py --run "$R" --expect-wait  # the pre-fix authority: wait
```

On a fresh island run, about 20 s after launch (a world just published is busy with every resident's first deliberation, and the resident's `think` can land after the walk). It joins two identities, holds a resident R and a second resident W with `set_behavior`, chooses a side of R where the bystander, put 8 m out, sees R (towns differ per world), and reads R's `deliberation` scene after a `think` leaf (admin `set_behavior`; speech no longer requests a deliberation). Step 0, R's first sight of the player walking in from 14 m, runs once per world and is logged `NOT OBSERVED` when R gives no line (the way in blocked; before strangers-1 also a crowd, where strangers were not announced). Since strangers-1 first sights of one look share one line, the player its subject or object; each part of the line is checked on its own. Evidence: `approach.json`, `actions.log`.

## A first sight asks a mind, never a player

Since `first-sight` (2026-11-12; docs/FIRST_SIGHT.md). With the world's `first_sight_thinks` law on (and `first_sight_gap_s` 0, both set as the admin), the player's character P is placed beside S, a resident it does not know, and R, a resident that has never seen P:

- P, played, has no `deliberation` row, no first-sight line in `my_experience` (a played body's look tells it none), and `character.ai` stays false;
- `seen_characters` has S with an empty `name` and `label` `a stranger`;
- R's `deliberation` reason holds a first-sight line naming "a stranger" (P is the stranger to R);
- `set_world_law first_sight_thinks` from the player's identity is refused ("admin only").

```bash
.agents/skills/verify-player/scripts/first_sight.py --run "$R"
```

Any seed with AI people (the default `world`). Writes `RUN/first_sight.json`. The laws are restored.

## Gotchas

- Minds use the same projection and the same skill: a mind's scene lists `health: "34 of 60"` while its appraisal holds. That path is a graph leaf or a deliberate act, not driven here.
- The resident must stand still for the 6 m reach; the script picks one whose segment has ended (`next_ms` at rest).

## Remains

On a fresh default-seed run, use `scripts/seen_remains.py --run "$R"`. The run's player joins with its own identity. Admin places and kills 20 scene actors before bringing the player to the field. The player can read every nearby remains structure and receives no `You notice` experience. Its identity is refused access to the private `seen_structures` table.
