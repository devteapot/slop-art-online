# char-found stage 2: the head, a capped Fable session (brief, prepared 2026-11-27)

**Status: prepared, NOT started.** It starts only when the owner says yes to one capped Fable 5.2 session, relayed by the general coordinator. No paid calls before that.

## Why this session exists
Stage 2 of the character foundation (`char-found`) stalled on the head. Astra fitted Cora's existing head (from `docs/char-live-2/final/`) onto the new body. The result reads as **one face for everyone**: the woman, man, elder and child share Cora's face, resized. The jaw also forms an angular shelf below the ear in profile, worst on the man, with a notch on the woman's jaw line, and the elder reads young. The checkpoint is `char-found` 3145c1e25 (head) / 06cbb63e6 (with the hands). Its notes are `docs/char-found/head-checkpoint.md`, and the sheets are `docs/char-found/head-expressions.png`, `lineup.png` and `live-face.png`.

The body (stage 1) is done and judged (32/40, passed). It is B2's single parametric cage on the shared 82-joint skeleton of `lookdev/anim/own-clips.glb`, with 9 morphs (Sex_Male, Sex_Female, Age_Child, Age_Elder, Build_Heavy, Build_Slim, Face_Round, Face_Long, Jaw_Square), L1 and L2 levels, and 87/87 clips. The hands are done. The hair waits for this head.

## The goal: one modelled anime head that varies
- **One head mesh that varies through the same morph system** as the body (sex, age, face shape). It is not a fixed face, and not one file per person.
- **What it must show:**
  - the **woman** with softer features;
  - the **man** with a brow ridge and a broader jaw;
  - the **elder** reading old: sunken cheeks, heavier lids, a softened jaw line, a longer nose and ears;
  - the **child** with a rounded head and large eyes.
- **A clean jaw edge in profile** for every mix: no shelf, no notch.
- **Anime-leaning toon style.** Blue Protocol is the closest of the owner's references. Cora's sheet (`docs/cage-taper/cora.webp`, `docs/char-live-2/final/`) sets the craft standard: real sockets, lids, a mouth that opens, and brows.
- **Keep the face pipeline that already works** at the checkpoint, so the client's face shading and driver work unchanged:
  - the VRoid/VRM 0.x conventions (`J_Bip_*` bones, material name tags, a VRM block);
  - the **15 `Fcl_*` expressions** with their VRM groups;
  - the face's designed normals (`face_normals.py`) and its drawn shadow map (`.face.png`).
  - The game drives `Fcl_EYE_Close` and `Fcl_MTH_A`. See docs/CHARACTERS.md: the Export row, "Expressions", and the brows and lashes.
- **A reduced far head** for the far LOD: a 12×12-style grid with no openings, the features painted, no expressions. See the "far model" row in docs/CHARACTERS.md.

## References
- The **owner's quality refs** are in `~/archive/owner-quality-refs-20261126/ref1–6.png`: Corepunk, a League of Legends model, Blue Protocol, SUPERVIVE. They are a bar for detail, silhouette, material and readability. **Read only: never copy them into any output, never commit or upload them, and never reproduce their characters or designs.**
- Our identity references: `docs/cage-taper/cora.webp`, `docs/char-live-2/final/`, `living/tools/characters/reference/`.
- The laptop's advice, as Neon placed it in stage 2 (`~/.local/state/bakeoff/LAPTOP-ADVICE-20261127.md`):
  - fuller sculpted volume, in the 6.5–7 heads range;
  - bake a gentle top-down value gradient and crevice AO into the face texture;
  - per-mesh `_OUTLINE_WIDTH`: face about 0.4×, outer hair and body 1.0×.

## What "done" means (judged in our renderer, not in Blender)
The session's work is judged **only** on sheets made by the shared sheet script (`living/tools/blender/found/head_sheet.py`, see below). Its baseline is today's head, saved as the known answer before the session starts. Done means:
1. **Distinct faces by sex and age.** On the head sheet's neutral row and the lineup, the woman, man, elder and child are told apart at a glance from the face alone. The Neon critic must not have to squint (the GC's bar).
2. **The elder reads old** in the face: front and profile.
3. **Clean profile jaw edges** on every mix: no shelf, no notch.
4. **Expressions intact:** all 15 `Fcl_*` targets per mix, plus a live blink and speech proof through the game's face driver (as `docs/char-found/live-face.png` at the checkpoint).
5. **Checks green:** clips 87/87, `skeleton_check`, `clips_compare` (0.00° and 0.0 cm drift), and strain within the stage-1 bands.
6. **The far head exists** and matches its near head's identity at Middle and play distance.

## Porting it back into the generator (nothing manual on the path)
- The head must be **produced by a script** under `living/tools/blender/found/`, called from the same generator entry point as the body and hands, with the morph weights in and a GLB out.
- **Sculpting in Blender is allowed only to author source data,** for example shape-key deltas or a base mesh saved as a `.blend` the script loads. The script must regenerate every mix from parameters with no hand step.
- Commit the sources (scripts, any `.blend` the script reads), the sheets and a README to `char-found`. Push. Don't merge.

## Stop rules (enforced in code by `living/tools/blender/found/session_guard.py`)
- **Wall clock: 2 h** from `session_guard.py start`. **Every iteration begins with `session_guard.py check`**, and the session stops when it exits non-zero.
- **The spend cap:** Fable shares the Claude weekly pool, and its spend isn't visible from inside the session. So the cap is enforced as **at most 6 judged sheets (iterations)**, as well as the 2 h. The coordinator also cancels the task at 2 h 10 m as a backstop.
- **The no-gain rule:** after each judged sheet, the Neon critic's score goes in with `session_guard.py record --score N`. The session **stops when two consecutive sheets show no gain** over the best so far.
- **At a stop, whatever the state:** export what exists, render the sheet, commit, push and report.

## The model and rules
- **Model:** Claude Fable 5.2, high effort. **One session only**, the owner's exception to "no Fable". No subagents, no workflows, Ultracode off.
- **House rules:** `~/.local/state/devbox-queue/house-rules.md`, plus:
  - Blender through `~/.local/share/slop-tools/build-bin` with `JOBS=3`;
  - cargo under `flock -s ~/.local/state/slop-build/gate.lock`;
  - never living-check or merge;
  - keep 45 GB free.
- **The report:** start and end times, the iteration count with each sheet's score, which stop rule fired, the head, the sheets, the checks, and what's weak.
