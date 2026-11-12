# Two free audits: confabulation and who lives where (2026-11-12)

Ideas 5 and 7 of [the mind research list](MIND_RESEARCH_IDEAS.md), approved for free work. Branch `ideas-audits`, from origin/main. Both audits are read-only over existing trial evidence on the Spark: no model call, no database, no build. The tools are [`confab_report.py`](../living/tools/confab_report.py) and [`homes_audit.py`](../living/tools/homes_audit.py); their docstrings define every class and measure.

Evidence read, all on the Spark:

| Batch | Where | Runs |
|---|---|---:|
| ar2 | `~/dev/slop-runs-arrive/.local/living/trials/ar2` | 28 |
| st1 (Aldous only) | `~/.t3/worktrees/slop-art-online-t3/t3-22f3c8bb-31c48b5f368e04ab/.local/living/trials/st1` | 8 |
| st2 | `~/slop-stage2/.local/living/trials/st2` | 3 |
| st2b | `~/slop-trials2b/.local/living/trials/st2b` | 4 |
| bi1 | `~/dev/slop-runs-arrive/.local/living/trials/bi1` | 4 |
| r2d | `~/dev/slop-cm-r2d/.local/living/trials/r2d` | 10 |

st0 was a fake-model run with canned lines, so it is left out. r2d is not in the homes audit: an arena has no homes.

```bash
python3 living/tools/confab_report.py ar2 st1 st2 st2b bi1 r2d --out OUT   # batch directories as above
python3 living/tools/homes_audit.py ar2 st1 st2 st2b bi1 --out OUT/homes.json
```

## 1. Confabulation about one's own deeds, possessions and knowledge

**Method.**
- The lines are every chronicle `speech` row of a thinking character: 15,043 rows across the six batches. A repeat within 2 minutes is one row.
- The scripted player's lines are left out.
- Each sentence is matched against nine first-person claim classes (`know`, `know_not`, `read`, `gave`, `have`, `have_not`, `made`, `ate`, `been`).
- Each claim is checked against the speaker's record at that moment:
  - the scene snapshot before and after the line, which gives `pack`, `knows_how_to`, hunger and position;
  - "You know how to:" prompt lines;
  - `know_how` rows;
  - the chronicle's gives, builds, plants and lessons;
  - the speaker's own experiences: `experiences_all` where the batch keeps it, and the timed "Recent experiences" lines of its prompts in every batch;
  - deeds others witnessed;
  - census activity.

A deed with no record counts as contradicted only when the line dates it within the run ("just", "today", "already" and the like). Otherwise it is `undated`, because a seeded person's authored past is not in the record. Every claim keeps its evidence in `confab.json`, and `confab.md` shows the evidence beside each flagged line.

**Result.** 252 claims, of which 179 were supported, 38 unsupported (no snapshot near enough), 7 undated and **27 contradicted**.

| Batch | Lines | Contradicted (tool) | Per 100 lines | Real on hand check | Per 100 lines, real |
|---|---:|---:|---:|---:|---:|
| ar2 | 3,044 | 4 | 0.13 | 4 | 0.13 |
| st1 | 35 | 0 | 0 | 0 | 0 |
| st2 | 1,785 | 2 | 0.11 | 1 | 0.06 |
| st2b | 2,477 | 6 | 0.24 | 6 | 0.24 |
| bi1 | 7,639 | 15 | 0.20 | 12 | 0.16 |
| r2d | 63 | 0 | 0 | 0 | 0 |
| **All** | **15,043** | **27** | **0.18** | **23** | **0.15** |

Per arm, the tool's rate ranges from 0 to 0.66 per 100 lines. The highest is st2b's LS + cues arm, which is one child's five lines (Posy, below). The arms' table is in `confab.md`. One replicate per arm in st2, st2b and bi1 cannot rank arms.

**Hand check: all 27 flags, of which 23 (85%) are real.** The 4 doubtful ones:
- Ife (st2): "Bet I can read the sign before you can". A dare, not a statement.
- Cal (bi1 longing): "I don't know the fire's way yet". Cal knows fire but not cooking, which is likely what he meant.
- Uma (bi1 provided): "Papa, I ate some berries". Only 2 snapshots in the window.
- Lio (bi1 provided): "so I ate it with thanks". An undated story.

The checks above were made on the final version of the patterns. An earlier version flagged 38, and the false positives it taught are now excluded and listed in the docstring:
- "I've wood to cut", "I've crucibles to make": a task, not a thing held;
- "I've kelp stored": a store;
- "I gave you my name": a name, not an item;
- "read the water": not writing;
- "before I've eaten": not a claim that it happened;
- "a net of promises": a figure of speech.

**What kind of confabulation it is.** Two kinds make up almost all of it.
- **Offering food one does not carry** (12 of 23). Nearly all is fish, in the hamlet, where cooked fish piles up in the stores. Example: the speaker says it holds fish while the pack shows a spear.
- **Claiming letters one does not have** (6 of 23). Mostly children.

Deeds such as made, gave and read are rarely claimed and rarely wrong.

**Examples** (speaker, line, contradicting record):
1. bi1 control, Cal Reed to Lark: "I've got fish in hand for you." The pack 0 s before and 47 s after: `{"spear": 1}`.
2. bi1 control, Mara Vane to Nia: "stay put, I've got fish in my hand for you this very moment." Pack: `{"berries": 1, "wood": 6}` both sides.
3. bi1 longing, Brisk Marrow to Tobin: "Ada's hungry and I've fish for her." Pack: `{"stone": 3, "tablet": 1, "torch": 1}`.
4. bi1 provided, Teodor Vane to Brisk: "I've wood for a tablet and a trade to put in your hands." Pack: `{"berries": 4, "stone": 3}`.
5. st2b LS + cues, Posy Fenwick, five lines in 20 minutes: "I've got a shard to trade her" and "I've got a shard worth trading". Her pack was empty in every snapshot.
6. ar2 arrive-all r4, Ilsa Hale to Mara Vane: "I know my letters — my mother drilled them into me at the river mouth. I'd take that trade, carpentry for reading and writing." Her know-how at the line: cooking, fire, storage.
7. ar2 control r3, Lio Reed to Cal: "Uncle Cal, I know my letters … I'll teach you to write them". Know-how: trapping.
8. bi1 spaced, Lio Reed to Wenna: "I read the sign with my own eyes." He did not know writing, so he could not have read.
9. bi1 control, Sefa Reed: "Sol's fed from the store, and I've eaten." Her hunger in the 19 snapshots of the 20 minutes before: 35 rising to 46, never falling.
10. ar2 control r1, Ilsa Hale to Pim: "I'll show you how to fish the line, like I promised." She does not know fishing.

**Limits.**
- The rate is a floor. The patterns find about 1.7 claims per 100 lines, and they miss paraphrase ("my satchel's heavy with fish").
- `have` depends on snapshots within 180 s on both sides; 38 claims had none.
- `made` and `read` are complete only where `experiences_all` exists (ar2, st1, st2, st2b). bi1 and r2d use the prompts' recent experiences.
- `been` found no checkable claim.
- A contradicted claim is words against the record, not proof of intent. A deliberate lie is not told apart: the thought before the line would say.

## 2. Who lives where: can a mind know and remember someone's home?

**Verdict: partly. The paths exist end to end, and minds use them. But the authority shows whose a house is only while its owner stands near the observer, so minds attribute houses wrongly about a quarter of the time.**

**The paths, traced in code** (main `e7d41209`):
- **Authority truth.**
  - A house is a `structure` with an `owner` (`seed.rs` `house_at`).
  - Each character has a household home, `character.home_x/home_y`; `records::home_of` gives it to the rules only, as `actor.home` and `target.home` in `act.rs`.
  - The mind is told only its own home: the seeded place `"home"`, `given`, in "# Places you remember".
- **Shown.** A deliberation scene lists up to 10 structures in sight. A house carries `home_of` and `by` from `common::owner_label` ([common.rs](../living/authority/src/common.rs)).
  - Under the `owner_shown` law (`knows || shows`), the owner is named only if the observer knows the owner's name (`perception::knows_name`).
  - Even then, the name comes from `label_for(observer, owner)`, which applies `perceived_of` to **the owner's own current distance from the observer**. Under Cullet's laws (`known_within` 24 m; the hamlet uses them too), a known neighbour's house therefore reads `"home_of": "someone too far away to make out"` (st2, st2b builds) or `"a stranger"` (ar2, bi1 builds) whenever the neighbour is out.
  - Players' clients name owners the same way, through `my_known_names` and the same law (`living/game/src/verbs.rs`, `looks.rs`).
- **Told.** "I live by the quay" is ordinary speech. Consolidation may turn it into a place or an edge; nothing in the rules records it.
- **Kept.** Minds keep homes two ways:
  - named places (`places`: name, x, y, which become `place` rows and "# Places you remember"), such as "Gwil Stannard's house" and "Teodor's door";
  - free graph edges in Neo4j such as `person:61 —LIVES_AT→ place:benedikts_hall`.

  No schema exists for "lives at"; the open graph allows it.
- **Recalled.** Situational recall brings those edges back.
  - In st2b, 455 of 1,878 think prompts held one under "# What comes to mind", e.g. "Benedikt Orme (person:61) —LIVES_AT→ place:benedikts_hall (84%)".
  - In bi1, 210 of 8,165 did.
  - So the prompt can already show the equivalent of "X lives in the house by the quay", in graph shorthand. Recall in talk prompts was not counted.

**How the scenes labelled houses** (every house in every think or deliberate scene):

| Batch | Owner named | Owner as a far or unnamed figure | No owner shown (not known by name) |
|---|---:|---:|---:|
| ar2 | 4,923 (39%) | 7,753 (61%): "a stranger" 6,103, "an old stranger" 1,650 | 0 |
| st1 | 103 (42%) | 129 (53%) | 12 |
| st2 | 830 (22%) | 2,226 (60%): "someone too far away to make out" | 663 |
| st2b | 1,260 (22%) | 3,468 (60%) | 1,089 |
| bi1 | 20,179 (49%) | 20,820 (51%) | 0 |

The hamlet's twelve people know each other's names, so "no owner shown" is 0 there. Yet half the time a house reads as a stranger's, because its owner is away from it.

**Homes kept, checked against the truth.** The truth is the houses a scene named as someone's, plus each resident's own seeded home place, so a partner or child of the owner counts. A kept place counts as right within 10 m.

| Batch | Right | Wrong | Cannot tell | Minds keeping one |
|---|---:|---:|---:|---:|
| ar2 | 14 | 23 | 4 | 37 |
| st1 | 2 | 0 | 6 | 4 |
| st2 | 51 | 31 | 14 | 64 |
| st2b | 38 | 11 | 11 | 47 |
| bi1 | 78 | 26 | 8 | 44 |
| **All** | **183** | **91** | **43** | |

Of homes that can be checked, 67% are right and 33% wrong. Houses stand about 6 m apart in Cullet, so 10 m can credit a neighbour's house.

**Examples.**
- Right:
  - Alder Fenwick (st2b) kept "Gwil Stannard's house" 0.7 m from it.
  - Mara Vane (bi1) kept "Teodor's door" 4.7 m from Teodor's house.
  - Aldous Quill (st1) kept "Lorcan Vane's house" 2.5 m from it.
- Wrong:
  - Mara Vane (bi1) kept "Oren's house by the reeds" at (34, 21). Oren's house is at (68.5, 17.5), 35 m away. The place is 6 m from Wenna Reed's house, which her scenes often labelled "a stranger".
  - That belief came back in later prompts: "Oren Hale —DWELLS_AT→ Oren's house by the reeds (50%)".
  - Roos Achterberg (st2b) kept "Otto Brandt's house" 59 m from it.
  - Wick Marl (st2) kept "Aldous Quill's house" 29 m from it.
- The cause of each wrong one is not established. A house's label flickering with its owner's whereabouts is the likely one, and the code makes it possible, but these numbers do not prove it.

**Said.** Lines placing a home are common in the hamlet, where people visit each other: 106 in bi1, against 5–12 in the others. Examples: "first light finds me at Teodor's door with his fish"; "I've a fish to carry to Ilsa's hearth east". The audit does not judge whether a spoken home was right.

**What is missing (stated, not proposed).**
- Whose a house is should not depend on where its owner stands. Today it does, through `owner_label` → `label_for`. A player's client names houses from `my_known_names`, which does not read distance; the lines a player is told from the authority (a theft from someone's store) did. *(Corrected 2026-11-12 by house-owner-label, §3: this line said players were affected the same way.)*
- A household is shown by one owner's name. A partner or child who lives there is not named with the house.
- Nothing tells the mind "lives at" as a perception. It infers it from labels and talk, which is the intended path, but it infers from the flickering label.

## 3. Follow-up: the house-label fix (house-owner-label, 2026-11-12)

Branch `house-owner-label`. The rule, as approved: a house names its owner when the viewer knows them (`perception::knows_name`, the shared regard answer) or when the house shows its owner (`owner_shown`, the kind's `shows_owner`). Where the owner stands never matters. Details and checks: [PERCEPTION.md](PERCEPTION.md#whose-a-thing-is-and-what-places-are-called-owner-known-2026-11-12).

**Every place the label is built.**
- The authority, `common::owner_label`: a mind's scene (`by`, `home_of`); its notice lines ("You notice a house built by …"); its region summary ("you see Wenna Reed's house").
- A witnessed theft, "{a} took … from {b}'s storage": `{b}` was the owner's person label, with distance. It now uses `perceive::witnessed_owned`.
- The client: `looks::structure_name`, from `structure.owner` and `my_known_names`. It never read distance and is unchanged.
- A second leak, found by verify-minds and fixed: lines about an owned thing carried the owner as their subject. The mind service then tagged them with the owner's far handle ("… built by Walker2 {someone too far away to make out=#1000000046}"). An owner the line did not name was still tied to it. Now the owner is carried only when the line names them, by id (`percept_owned`).

**Mara's case: labelling, not memory, as far as the record shows.**
- In bi1 control, before her consolidation wrote "Oren's house by the reeds" at (34, 21), her scenes showed the house at (38.5, 24.5), 6 m from that spot, 19 times. Every time it read as `home_of: "a stranger"`: it is Wenna's house, and Wenna was away.
- Oren's own house, at (68.5, 17.5), was named 22 times and labelled "a stranger" 9 times.
- The only nearby line naming Oren's house was a region summary at (30, 16): "you see Wenna Reed's house, campfire, Wenna Reed's storage, Oren Hale's house". It gives no positions, and Oren's house was 38 m away.
- So she had a nameless house beside her and Oren's name in a list. With the fix, that house reads "Wenna Reed", the only label it could take for her.
- Whether a model still forms such beliefs with right labels needs a paid run. A fake model writes canned memories, so a fake run can show only the labels; see the fake hamlet run below.
- The summary line's lack of positions remains. It is memory's raw material, not a label.

**The fake hamlet run** (`hol1`, `hamlet` × 1, 20 minutes, the fake model, Cullet's laws with `known_within` 24 m; built from this branch).
- `homes_audit.py`: of 970 house sightings in think and deliberate scenes, 824 name the owner, 146 show none (the viewer does not know the owner by name), and **0** read as a far or unnamed figure. In bi1 it was 51% (20,820 of 40,999).
- No homes were kept as places and no lines placed one, because the fake model writes no such memories. Whether wrong home beliefs still form with right labels is a paid question.
- Evidence: `.local/living/trials/hol1/` in this worktree. The world was deleted by `trials.py clean` (paused first, SQL 404).

**A note for later (#5): the talk prompt and one's own pack and letters.**
- A conversation turn (`talk_user`, `prompts.rs`) shows who one is, the other, recall, lately, the scene line, the body, standing proposals and dealings (`between`), and the conversation. It shows **neither the pack nor the know-how**. Iteration 8's lines were never merged.
- Measured on bi1 control's 556 talk turns, from each speaker's latest think scene: "- You carry (as you last looked): …" and "- You know how to: …" add 102 characters on average (p50 103, max 136), about 25–30 tokens. That is about 1.3% of the mean talk prompt (2,268 tokens).
- The lines are dynamic, so they are uncached input: about $0.000004–0.000009 per talk call at glm-flash or deepseek-flash input prices (`trials.py` `PRICES`).
- Per batch: bi1 (2,283 talk calls) about 68k tokens, $0.01–0.02; st2b (1,085) about 32k tokens, under $0.01.
- Not changed: it waits until a batch shows confabulation rising.

**The client (`living/game`).** No change is needed for this bug: `looks::structure_name` already names an owner from `my_known_names`, never from distance. Two differences remain from what minds are told, for later:
1. A world's own `owner_shown` law: the client hard-codes `knows` and does not call the compiled script. It could use `Scripts::owner_shown(known, shows, kind)` from `living_rules`, which it already compiles.
2. `shows_owner`: no shipped kind sets it. A kind that did would name its owner to minds, but the client would still say "storage". The client would need the kind's trait (`Scripts::structure(kind).shows_owner`) and the owner's name for an owner not in `my_known_names`. No player row carries that name today, so it would need an authority view: a shape change, not proposed here.

## Not covered

- Paid runs; neither audit calls a model.
- Talk-turn recall of homes.
- Whether kept homes were used: walks to them, and gives delivered there.
- A replicate spread for either measure.
