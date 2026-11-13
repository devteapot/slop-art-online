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

## Body sex

Since `sex-1` (2026-11-13; docs/LIVING_CORE.md "Body sex"). The `body-sex` case runs on the hamlet at a fast pace (`body_seed`, every resident giving `sex`), with the fake model, Oren Hale's and Ilsa Hale's minds, and a newcomer from `spawn_crowd`. It asserts:

- **The self line.** Oren's prompts carry "You are a man." after the body line (`Minds::body_line`, the rules' `sex_words()`).
- **Remembered.** His relations list his wife, placed out of sight 30–60 m off, as "Ilsa Hale (#id, a woman)": he made her out at home, so the authority wrote his `sex_seen` row for her.
- **The scene, near.** The newcomer 3 m off is an entry with `"form"`, the newcomer's word, and `"who": "a stranger"`. No label in the scene carries a sex word.
- **The scene, far.** Under an overlay that makes everyone past 4 m `far`, the newcomer at 6 m is a figure under a handle (≥ 1000000000), with the far label and the same `form`. No entry carries the newcomer's id.
- **The talk header.**
  - The newcomer says a line to Oren 1.5 m away: his talk prompt heads "# You and a stranger (#id, a woman|a man)": made out at 3 m and 1.5 m, he remembers its body (`sex_seen`).
  - Then Ilsa does: "# You and Ilsa Hale (#id, a woman)".
- **Kin words.** Pim (their child) says "Mother, …" to the room beside both, and Ilsa is told she was named while Oren is not. "Father, …" the other way round.
- **The newborn.** Brisk and Edda Marrow (graph-only) start a family. Once the child is born it has a `sex` row, and the mind, restarted with the child in `LIVING_ONLY`, makes its birth identity call: "Newborn: Name (#id, <its body by stage: a baby girl, a boy…>)." Each parent's body appears exactly when the newborn has a `sex_seen` row for them.

Prompts in `prompt-near.txt`, `prompt-far.txt`, `prompt-talk-stranger.txt`, `prompt-talk-wife.txt` and `prompt-birth.txt`, and checks in `body-sex.json`.

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case body-sex
```

## The perception boundary

The Spark's condition, 2026-11-13. A prompt never states the sex of someone the mind has not perceived and does not remember. The mind service reads the whole `sex` table as the owner, and the boundary is drawn where prompts are built: another person's sex comes only from the scene (in sight, Full or Far) or from the authority's `sex_seen` row (the talk header too; a voice heard from out of sight gives none). That row is written when the mind's character first made the person out at Full.

The `sex-boundary` case runs on `boundary_seed`: the hamlet at the body case's pace, with Lio Reed grown and given no sheet, and Mara Vane, from the other settlement, as his parent. Oren's and Lio's minds run with the fake model, and a newcomer comes from `spawn_crowd`.

- **Allowed:**
  - the newcomer 3 m off: the scene's `form` (Full);
  - the newcomer at 6 m under the far overlay: the figure's `form` (Far);
  - Ilsa (Oren's row, written when he made her out at home), moved out of sight: in his relations, and in his talk header when she speaks to him from 5 m behind him under facing sight (`fov_on`: heard, not seen).
- **Not allowed:**
  - Wenna Reed: in Oren's relations but never seen (no row). Not stated in his relations and known people, nor in his talk header when she speaks to him from behind him (heard, not seen), nor when Ilsa names her in a line.
  - Mara in Lio's facts (`Background:` identity call): a parent never met.
  - Brisk in the newborn's birth prompt: killed (admin `kill`) as soon as the couple is expecting, before the minds start, so the child, born where its mother stands, never sees him. Moving him off was not enough: in `minds-sex2-c` the child, born beside him, made him out. The mother's body appears exactly when the newborn's row for her exists.
- **The scan.** Every prompt the three minds were sent, the facts and birth calls included, is scanned (`sex_statements`: "(#id, a word)" and a JSON object with the id and `form` or `is`). Outside the scene, each statement of another's sex must be backed by that mind's `sex_seen` row (`unbacked.json` lists any that are not).

Evidence: `sex-boundary.json`, `prompt-lio-facts.txt`, `prompt-near.txt`, `prompt-far.txt`, `prompt-talk-ilsa.txt`, `prompt-talk-wenna.txt`, `prompt-birth.txt` and `unbacked.json`.

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case sex-boundary
```

**The mutant.** `known_sex` (`living/mind/src/mind.rs`) stating a person's sex without the row, as the first sex-1 build did (anyone known by name or relation). Build it into a copy of the binary, run the case with it, and expect failure:

```bash
cp living/mind/src/mind.rs /tmp/mind.rs.orig
python3 - <<'PY'
p = 'living/mind/src/mind.rs'; s = open(p).read()
s = s.replace("let row = self.conn.db.sex_seen().iter().find(|r| r.observer == me && r.known == other)?;",
              "return self.sex_words_of(other);\n        #[allow(unreachable_code)]\n        let row = self.conn.db.sex_seen().iter().find(|r| r.observer == me && r.known == other)?;", 1)
open(p, 'w').write(s)
PY
cargo build --release --manifest-path living/Cargo.toml -p living-mind && cp "$CARGO_TARGET_DIR/release/living-mind" .local/living/mind-sex-mutant
cp /tmp/mind.rs.orig living/mind/src/mind.rs && cargo build --release --manifest-path living/Cargo.toml -p living-mind
LIVING_VERIFY_MIND_BIN=$PWD/.local/living/mind-sex-mutant .agents/skills/verify-minds/scripts/verify_minds.py --run "$R-mutant" --no-unit-tests --case sex-boundary   # must FAIL
```

`LIVING_VERIFY_MIND_BIN` (in verify-llm's harness) runs a mind binary built elsewhere. The driver still builds the tree's own.

