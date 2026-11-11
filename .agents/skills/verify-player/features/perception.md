# What a player perceives of others

Since 2026-11-09 (docs/PERCEPTION.md, "What an observer perceives of a target"). `seen_characters` is each creature's record through the script's `perceived_of` law, for this player: its name only when known (else a label such as `a stranger`), health as a band unless a skill reveals more. `appraise` (declared in skills.rhai like any skill) reveals exact health for 20 s to whoever uses it. Saying one's own name tells it to everyone who hears.

## Sub-features

- A newcomer perceives a resident as `a stranger` (empty `name`, a `label`), health as a band (`hp` -1); `seen_characters` has no `controller`, home, parents or `ai` column.
- `human_act {"do": "appraise", "target": {"id": N}}` is carried out (`skill_use` outcome "a stranger has 100 of 100 health"), and the appraiser's `seen_characters` row for N then carries exact `hp`/`max_hp`; a bystander beside it still has `hp` -1 and a band. The appraiser's `my_experience` holds "You look a stranger over: … of … health."
- After the reveal's 20 s the appraiser sees a band again.
- The appraiser says "Hello, I am <name>." and the bystander, who heard it, perceives the appraiser by name (`name`, `label`) and its experience reads "<name> said: …".
- **A walking player is perceived walking** (since `fix-perceived-moving`, docs/PERCEPTION.md "Activity derived from the body"). A player walking at a resident by `human_move` is in the resident's deliberation scene as `"doing": "walk → person"` (before: `wait`), and the resident's first sight of it reads "…, 8 tiles east, walk → person.". Standing, it reads `wait`. An AI resident walking the same line by `goto` reads `goto → person`, unchanged. A bystander player's client gets the same for both: the body moving in `seen_bodies`, no `seen_doing` row.
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
.agents/skills/verify-player/scripts/approach.py --run "$R"            # the fix: walk → person
.agents/skills/verify-player/scripts/approach.py --run "$R" --expect-wait  # the pre-fix authority: wait
```

On a fresh island run, about 20 s after launch (a world just published is busy with every resident's first deliberation, and the resident's `think` can land after the walk). It joins two identities, holds a resident R and a second resident W with `set_behavior`, chooses a side of R where the bystander, put 8 m out, sees R (towns differ per world), and reads R's `deliberation` scene after a `think` leaf (admin `set_behavior`; speech no longer requests a deliberation). Step 0, R's first sight of the player walking in from 14 m, runs once per world and is logged `NOT OBSERVED` when R gives no line (the way in blocked; before strangers-1 also a crowd, where strangers were not announced). Since strangers-1 first sights of one look share one line, the player its subject or object; each part of the line is checked on its own. Evidence: `approach.json`, `actions.log`.

## Gotchas

- Minds use the same projection and the same skill: a mind's scene lists `health: "34 of 60"` while its appraisal holds. That path is a graph leaf or a deliberate act, not driven here.
- The resident must stand still for the 6 m reach; the script picks one whose segment has ended (`next_ms` at rest).
