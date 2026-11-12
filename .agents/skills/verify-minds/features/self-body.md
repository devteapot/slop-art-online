# The body in "Who you are", and a grown mind's first identity

Since 2026-11-12 (branch `self-body`; docs/TRIALS.md, "Does a run-born adult's identity still describe a child?").

## Sub-features

- **The body line.** Every prompt's `# Who you are` ends with one perceived line: "Your body: 15 years old, an adult for a few hours." (`prompts::body_line`, from the `character` row's `stage`, `birth_age_days` and `born_ms`, the `world` row's `year_days`, `life_pace` and `day_ms`, and the species' life table under the world's `life_years` law, as the scene's `you.age` reads them in `perceive.rs`). It goes through `persona_text` (think, deliberate, consolidate, reorganize, fast, a player's lived consolidation) and the talk identity (`talk.rs`). It sits beside the persona: the persona row is never rewritten by it. Words: a baby, a child, an adult, old (people); newborn, young, grown, old (animals). How long: `describe_days` under a year of age, then years.
- **A stage change stays a lived experience.** The authority's `grew` percept ("You have grown up: you are an adult now." / "You are growing old: …") is unchanged; nothing rewrites the identity when the stage changes.
- **A grown mind's first identity** (`Origin::Grown`, `facts.rs` `grown_identity`): someone born in the world whose mind first starts when it is past childhood (a capped trial, a restarted service) gets an identity from facts, with no model call: "I am Vale, child of Brisk Marrow and Edda Marrow. My home is in Millbrook. …", its siblings and children, its inborn temperament (genes) and no values, goals, pastimes, calling or mood. Its mind gets `CHILD_OF` edges to its parents and the `parent` relation a newborn's mind starts with (`lived_under = world`). Before this it had no identity and no parents. The thought is `kind` consolidate, model `facts`, summary "… grown before my mind began."

## Driving it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case body
# with the CHILD_OF and parent-relation checks (privacy.py's scratch Neo4j):
LIVING_PRIVACY_NEO4J=slop-trials-neo4j:127.0.0.1:7699 LIVING_PRIVACY_NEO4J_ENV=<file with LIVING_NEO4J_PASSWORD=> \
  .agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case body
```

The case writes a scratch seed into its run directory: the hamlet (Cullet's day and laws) at a year of age every 20 real seconds, Lio Reed 7 (adult at about 160 s) and Cal Reed 51 (old at about 170 s). It builds that module in `$CARGO_TARGET_DIR/verify-body`. The mind thinks for Lio and Cal; Brisk and Edda Marrow live on graphs and conceive; a player talks to Lio.

Checks (`body.json`):

- Lio's talk prompt carries "a child for" before; after his row turns adult, his next talk prompt and his next consolidation prompt carry "an adult for".
- Cal's prompts carry an adult's line before and "old for" after he turns old.
- The couple's child grows up with no mind; the mind is restarted with it in `LIVING_ONLY`. Its persona names both parents, has no values, goals, pastimes, calling or mood, and was written with no model call (thought model `facts`, no identity request in the fake log). Its first prompt carries that identity and "an adult for".
- With Neo4j: `CHILD_OF` edges from its `self` to both parents, and `parent` relation rows for both; the run's nodes are deleted after.

## Gotchas

- The case takes 10–12 minutes: the child needs about 5 real minutes from birth to adulthood at this pace.
- Seeded people die of old age from 75 years: at this pace Teodor Vane (70) dies within two minutes. Nothing in the case depends on him.
- The case restarts the mind once (`shared.stop`, `launch_mind`); the second `world subscribed:` line marks the restart.
