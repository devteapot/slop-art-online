# Per-purpose model mixes

`living/configs/models.json` may name **mixes** beside profiles: per purpose, a profile (`"glm-flash"`), a profile with its own effort for that purpose (`"deepseek-flash@low"`), or one per stage of attention (`{"on_stage": …, "off_stage": …}`); `"*"` covers the purposes a mix leaves out. A mix name is accepted wherever a profile name is: `default`, `assign`, `rotate`, `stages`, `groups` and `species`. Design and evidence: docs/MIND_HARNESS.md, item 1.

## Sub-features

- **Purposes:** `think`, `deliberate`, `talk`, `consolidate`, `reorganize`, `internalize`, `judge` (`llm::PURPOSES`). A purpose a mix does not name (nor its parent, nor `*`) goes to the default route.
- **Effort:** the mix's `@effort`, else the profile's map for the purpose, else for its parent (`reorganize` inherits `consolidate`'s, so an older profile does not send reorganization at GLM's default `max`). `purpose_max_tokens` caps a purpose apart from `max_tokens`.
- **Stage of attention:** on stage while a human player is in the scene or was part of what the character lived within `LIVING_LOD_STICKY_S` (mind/lod.rs). It is tracked whenever the level of detail is on or any mix is staged; with neither, everyone is on stage.
- **Startup checks** (`ModelsFile::check`): every route names a profile, `profile@effort` or a mix; mixes name profiles, not mixes; purposes are known; a default mix covers every purpose. A mix with an unkeyed profile is disabled with a warning and passed over like an unkeyed profile.
- **Journal:** every exchange records `profile`, `effort` (what was sent), `mix` and `attention` (for a staged choice), so purpose × profile × effort can be read back.

Sources: `living/mind/src/llm.rs` (`Choice`, `Pick`, `ModelsFile::check`, `Llm::pick`, `request_body`), `living/mind/src/mind.rs` (`Minds::attention`, `Minds::watched`), `living/mind/src/main.rs` (contact events when staged).

## Driving it

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case mix
```

The case assigns one adult a staged mix over the two fake profiles. Nobody is near, so the first compile is off stage; a player joins, is placed beside them and speaks, which puts them on stage; a new request is then compiled on the on-stage profile at its own effort. `result.json` counts journal entries by purpose and attention; the check requires every purpose and stage to have been exercised, every entry's `profile` and `effort` to match the mix, and the fake log's `(model, reasoning_effort)` pairs to match what was journaled.

## Gotchas

- The fake server infers the purpose from the system prompt when `reasoning_effort` is a real level (`low`, `high`), not a purpose name.
- A staged mix turns attention tracking on even without `LIVING_LOD=1`; it changes which model is called, never how often.
