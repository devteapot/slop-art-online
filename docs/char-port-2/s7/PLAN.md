# char-port-2 · S7 · The four-body proof, its cost, and the gathered must-fixes (plan)

**Status: a plan, for the coordinator and then the GC. Nothing in it is built.** It carries out [PLAN.md](../PLAN.md) §5 (the four-body proof) and §6 (cost) on main at `7f73c04c8` (S6b merged), with the four must-fixes gathered since S4. **Its sheets go to the GC before S8; that is when the owner sees the whole result.**

## 1. The bodies and the arms

**The bodies:** the woman, man, elder and girl, char-port-1's (`gen_person.sh` presets `woman`, `man`, `elder`, `girl`: the same seeds, identities and types).

| Arm | What it is |
|---|---|
| **main** | Each body as main builds it with no port flag: what residents look like today. |
| **port** | The same body with the whole port on: `SLOP_PORT=jaw,jaw_shell,paint,neck,ink,hair,masters,faceprop`, plus S7's own (the beard, the eye-joy fix; §3). Each body keeps its own hair style, drawn with S5's profile hair. **The woman is also shown in `swept_braid`,** the S6 master. |
| **Cora** (the woman only) | Her session file, `docs/char-live-3/ink-batch-2/own-cora-live.glb`, beside a woman built from her resident line (`cora-stannard`: adult-f-c, auburn, seed 37053) in `swept_braid`. **To decide:** §2.10's hero overrides, which would carry Cora's own type values, paint and ink parameters, aren't built. I propose her resident line now and the overrides later (question 2). |

## 2. The sheets

One light for all: 11:00, soft film, springs off, main's client at S7's head, 1600×900. Each sheet is a picture plus a short page saying what to look at.

1. **The four bodies** (one page each), main and port side by side (and the Cora arm on the woman's):
   - portrait front (`0:8:0.36:0.88`), three-quarter (`-35:8:0.36:0.88`) and back (`180:8:0.36:0.88`);
   - Near and Middle, the game's play stops at 58°.
2. **Expressions:** all 15 keys at the close-up (`0:8:0.18:0.86`) on the four bodies, port arm; blink, eye-joy and the open mouth also on main, for the comparison.
3. **The S5/S6 hair** on the woman:
   - the six styles (`bob`, `long`, `braid`, `swept`, `short`, `swept_braid`) and the master's cuts `.2` and `.3`;
   - in black, brown, auburn and grey;
   - at portrait, three-quarter, back and Near; the plait at Near and Middle.
4. **The beard** (the GC's addition): the man and the elder, close (front and three-quarter) and at Middle, before and after the port.
5. **The must-fixes' evidence:** the closing-eye keys before and after (must-fix 1); `swept_braid`'s mid band (2); `cage_accept`'s per-type table (4).

## 3. The four must-fixes

**The rule for every measure used here** (PLAN.md §7): a known-answer test first.

### 3.1 The eye-joy sliver (from S4)

**The defect:** on the woman and the girl, a sliver of the eyeball shows above the eye-joy arc. S2's file has it too, so it's the eye's geometry against the skin in that key, not the ink.
- **Measure first:**
  - an eye-ID copy (as `ear_id.py`: the `Eye` and `EyeIris` materials in one fixed colour);
  - the close-up front and three-quarter of every key that closes an eye (blink, blink L/R, eye-joy), on the four bodies and the 21 types;
  - the eye pixels above the closed lid's line.
  - A known-answer test with synthetic frames.
- **Then the cause, then the fix** in the generator. The likely places are eye-joy's lid arc in `head_mesh`/`cage_head` and the extent of the eye's white and bowl behind the lid.
- **Acceptance (the GC's, S7's row):** no eye white or iris above a closed lid in any key that closes the eye; the blink and eye-joy stills; `brow_check`; 0 new skin crossings (S6b's `morph_new.py`).

### 3.2 `swept_braid`'s dark and brown mid strip (from S6)

- **Re-measure first:** `calibrate_bins.py` on the six styles, with main's S6b types installed. S6's finding: dark mid −5.7 luma, brown mid −7 blue, against ±5. The face changed under the hair since, so it may move.
- **If it is in band:** closed.
- **If it is still out:** S6's two remedies go to the GC to choose from:
  - a wider mid band on the sweep's own surface;
  - less stand-off at the hem.

  The mid band's tolerance isn't widened.

### 3.3 The beard (from the paused `origin/char-4-body-joins`)

**The port:** `8d1659ec5` and `537eb0457`'s `face_paint` part only. The neck lift is out (§9 follow-ups); the far-beard `shade_mean` target is accepted.
- **What it changes:**
  - `head_form.beard_cover`: cheek hair thins toward the sideburn, the mouth's corners stay bare, the edge is softer;
  - `face_paint`: the beard drawn in hairs at a density; the short beard's core restored;
  - `person.make_overlay`: the overlay's alpha is the painted coverage, not a thresholded difference, so the edge is soft;
  - `person.far_beard`: 1.5 mm off the skin, not 4 mm;
  - `shade_mean`: the far-beard grey target.
- **Merge state:** the branch forks before S2–S6b, which also changed `face_paint.py` and `person.py`. I'll port by hand and say what conflicted.
- **Behind a flag (question 1):** `SLOP_PORT=beard` keeps main's output identical.
- **Checks:**
  - `shade_mean --check` with the new target;
  - the audit on the beard overlays;
  - the beard sheet;
  - measured, each with its known-answer test: the beard's alpha over the lips (the mouth visible), the width of its edge's ramp (soft), and how far its upper line sits from the jaw.

### 3.4 `cage_accept.py`'s chin and jaw failures (from S1)

**On main:**
- 8 of 21 types within 0.03 H with faceprop;
- 3 flag off (S1–S4);
- 1 with no port at all.

**The pattern:** at 0.04 H (the chin) the built head is wider than the type's record by up to 0.06 H, and at 0.12 H narrower by up to 0.05 H. That's on the women's lines, the children and some men. adult-f-b, the reference's own type, fails too.

**What to find for each type:**
- what the check expects: the record's widths, from the reference measure;
- what is built;
- what S1 meant: its chin and jaw tapers, Cora's chin.

**Then one of two outcomes:**
- **A defect** (the cage missing the tapered shape S1 asked for): fixed in the cage.
- **S1 departing from the reference records on purpose:** `cage_accept` compares against the records with S1's tapers applied, with each type's change shown.

`cage_accept` gets its own known-answer test (a synthetic head of known widths through `reference/measure.py`'s path) before its numbers are used.

## 4. Measures (§5) and cost (§6)

**On the arms:**
- the front widths (the 2D measure for the face, as S6b) and the depth projections;
- `lidweight` and `noseweight`;
- hair spread, lift and depth;
- the hair and skin patches;
- the 20 colour checks (Cora arm);
- triangles (≤ 50,000 near; §6's estimate 36–40k for the woman in `swept_braid`).

**The check list on the final build** (as S6b's):
- crossings;
- brows and eye colours;
- the S4 audit on types, bodies and pages;
- shimmer;
- `face_types check`;
- `cage_accept`;
- expressions: all 15 move and neutral returns exactly;
- flag-off identity.

**Cost** (§6), on the dev-box:
- 8 composed near people, port against main (`slop` stripped), at Near 1600×900 and the 4K close portrait;
- the 64-resident Cullet crowd against its baseline;
- frame time medians over alternating runs, three pairs each, uncapped;
- **budget:** at most +0.3 ms at 8 near, at most +1.0 ms on the 64-crowd.

## 5. Order

1. **This plan, and §9 follow-ups in PLAN.md** (the neck lift). On `char-port-2-s7`.
2. **The baseline:** the four bodies, main and port arms, built at main's head; triangles; the "before" stills for the beard and the closing-eye keys.
3. **`cage_accept` (must-fix 4):** its known-answer test, then the per-type analysis (no build). Any cage fix comes here, because it changes every face before the sheets.
4. **The eye-joy sliver (must-fix 1):** the eye-ID tool and its test, the measure, the cause, the fix.
5. **The beard (must-fix 3).**
6. **`swept_braid`'s mid strip (must-fix 2):** the re-measure; the GC's choice if it is still out.
7. **The final builds and the check list** (21 types, the four bodies, flag off).
8. **The sheets, the measures and the cost.** Then the package to the GC.

**Checkpoints to the coordinator:**
- after step 3 (the `cage_accept` table and any fix);
- after steps 4–6 (the must-fixes);
- then the package.

**Effort:** about 12–16 agent hours, Opus at high effort.
- **Blender:** the 21 types about four times, and the bodies with each.
- **The client:** main's release build, renders only.
- **Rules:** JOBS=3 through the wrapper, no `living-check`, no paid calls, scratch builds only, the installed assets put back and checked after every swap.

## 6. Questions

1. **The beard and the eye-joy fix behind their own port flags** (`beard`, and `eyes` or under `faceprop`), so main's output stays byte-identical until S8 turns the port on? My lean: yes, their own flags.
2. **The Cora arm:** her resident line in `swept_braid` now, with Cora's own type values waiting for §2.10's hero overrides? Or build the overrides in S7 (laptop agreement needed)? My lean: the resident line now.
3. **A bundle at S7's head** (PNG and KTX2, as S6 and S6b did), or leave bundles to S8? My lean: one bundle, so the laptop can look at what the GC sees.
