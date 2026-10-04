# Model routing and keys

## Sub-features

- A keyed town group beats stage and rotation.
- A named assignment beats the group.
- Rotation uses id modulo rotation length.
- Without a configured group, child stage beats assignment.
- Missing keys disable profiles and default is the final route.
- A missing default key prevents service startup.

## How to get to it (user POV)

Edit the models file to select models for groups, names or children. Keys come from the named environment variables.

## Driving it with verify_llm.py

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case routing-group --case routing-assign --case routing-rotate --case routing-child --case routing-default --case missing-default-key
```

Each routing result records expected actor-to-profile mappings in `result.json`. Every journal entry for those actors must match. Model names must match the selected profile. The alternate profile has json_mode false, so its requests omit response_format. The missing-default case must exit nonzero before receiving requests.

## Gotchas

`Llm::person_profile` implements person precedence. `Llm::profile_for` implements assignment, rotation and default. `Minds::profile` resolves group background. Two adults and a child are selected from real authority rows. `set_background` prepares only the scratch scene. This map does not claim species-role or inherited-parent group integration; the existing unit tests cover bounded group ancestry.

See [pacing.md](pacing.md) for the added profile keys and startup validation.
