# What a player perceives of others

Since 2026-11-09 (docs/PERCEPTION.md, "What an observer perceives of a target"). `seen_characters` is each creature's record through the script's `perceived_of` law, for this player: its name only when known (else a label such as `a stranger`), health as a band unless a skill reveals more. `appraise` (declared in skills.rhai like any skill) reveals exact health for 20 s to whoever uses it. Saying one's own name tells it to everyone who hears.

## Sub-features

- A newcomer perceives a resident as `a stranger` (empty `name`, a `label`), health as a band (`hp` -1); `seen_characters` has no `controller`, home, parents or `ai` column.
- `human_act {"do": "appraise", "target": {"id": N}}` is carried out (`skill_use` outcome "a stranger has 100 of 100 health"), and the appraiser's `seen_characters` row for N then carries exact `hp`/`max_hp`; a bystander beside it still has `hp` -1 and a band. The appraiser's `my_experience` holds "You look a stranger over: … of … health."
- After the reveal's 20 s the appraiser sees a band again.
- The appraiser says "Hello, I am <name>." and the bystander, who heard it, perceives the appraiser by name (`name`, `label`) and its experience reads "<name> said: …".

## How to get to it (user POV)

Two players stand by a resident. One looks the resident over (the appraise act); their health bar shows exact numbers for a while, the other player's shows only how hurt the resident looks. When one player introduces themself, the other's nameplate shows their name.

## Driving it

```bash
.agents/skills/verify-player/scripts/appraise.py --run "$R"
```

On an island run (`$V launch --run $R --seed island`; best with `LIVING_PERCEPTION=scoped`). It mints a second identity (kept as `token2`), joins both players if needed, holds a resident still with `set_behavior {"wait": 120}`, and sets the scene with `place_at` (named in the report: not something a player can do). Evidence: `appraise.json`, `actions.log`.

## Gotchas

- Minds use the same projection and the same skill: a mind's scene lists `health: "34 of 60"` while its appraisal holds. That path is a graph leaf or a deliberate act, not driven here.
- The resident must stand still for the 6 m reach; the script picks one whose segment has ended (`next_ms` at rest).
