# char-port-2 · S7 · Closing summary

**S7:** the four-body proof, its cost, and the gathered must-fixes ([PLAN.md](PLAN.md)). Everything is behind port flags; with them off, main's output is byte-identical (78 of 78 files).

## Done

- **Must-fix 4, `cage_accept`:**
  - the jaw rises sooner behind the chin (port `jaw`);
  - a taper-aware re-baseline, with its known-answer test;
  - **21 of 21 types** pass ([cage-accept.md](cage-accept.md)).
- **Must-fix 1, the eye-joy crescent** (port `eyes`): the eye's parts are placed on the open eye's plane in every state.
  - **0 eye pixels on the closing side in every closing key, on 25 heads.**
  - Main still shows the crescent until the flag is turned on in S8 ([sheets/expressions-port-main.png](sheets/expressions-port-main.png)).
- **Must-fix 3, the beard** (port `beard`): the beard port, with the GC's option (a full beard's core near opaque).
- **Must-fix 2, `swept_braid`'s mid strip:**
  - remedy (a): the cut's own t2 of 0.65, in the generator, on its own hair page;
  - the six-style calibration passes;
  - the cuts' side volume is accepted as it is.
- **The face proportions** (`faceprop`):
  - **The pose:** bind is the acceptance pose (hair-mirror).
  - **The measure:** pinned by the laptop's orthographic measuring view, with its known-answer test.
  - **The row:** defined by landmarks, 0.2967 of the way from the eye line to the chin, the chin from a chin-ID frame.
  - **2D against 3D:** they agree within 1% ([ortho/](ortho/README.md)).
  - **The re-derived factors:** every class within ±2% of 1.751, the children of 1.80.
  - **elder-m at 0.962:** bounded by `cage_accept`, not the formula.
  - **The ears:** 42 of 42 within 0.47 ± 3%.
- **The full check list** on the final builds ([final/](final)), all passing:
  - `cage_accept`, `face_types` and the jaw order;
  - crossings: none above main's;
  - `shade_mean`, the audits, the pages audit and shimmer;
  - the eye check and the six-style calibration;
  - lid ink depth about as S6b's.
- **The sheets,** port against main, idle and bind ([sheets/](sheets/README.md)):
  - the four bodies, the expressions, the hair and the beard;
  - the elders in their own looks;
  - Cora's resident line, labelled "not her hero file".
- **§6 cost** ([cost/](cost/README.md)):
  - +0.07 ms at 8 near (limit +0.3);
  - +0.12 ms at the 4K close (+0.3);
  - +0.07 ms on the 64-crowd (+1.0);
  - `swept_braid`'s own page: +1 material and pair, within the run-to-run spread.
- **The bundle** ([bundle/](bundle/README.md)): PNG and KTX2, every check passing; the delivery is held.

**Found and corrected on the way:**
- **The idle pose:** idle 2.0 s turns the head, which had distorted S6 and S6b's image measures.
- **The cheek row:** the 2D row sat 12 mm lower than the 3D's.
- **A calibration artefact:** `calibrate_bins`' band masks moved with a trial t2 that the drawn files lost.
- **The `--params` fault:** a generator dump passed back builds seed 0's man. It hit S7's Cora builds and the first town check, both rebuilt. The shipped residents are not affected (traced in code, and all 64 checked).
- **The one-eye keys:** they are counted on the closing side.
- **T-posed body renders:** the person files carry no clips, so the bodies are now drawn as composed lines.

## Open

- **The coordinator's notes on the sheets,** held for the owner:
  1. the port man's beard is patchy, with the jaw bare in the side view;
  2. the port's long hair has a hard dark lower band at the back;
  3. Greta's cheek-to-jaw seam, on both arms;
  4. age at Near and Middle reads only from hair and coat.

  The frames that answer 1–3 are kept.
- **S8** (the coordinator's order):
  - fix the `--params` round trip, with a round-trip test;
  - re-centre the `swept_braid` master's rear stations (about 0.53);
  - narrow elder-f-b's spread;
  - keep the master to women and girls;
  - then switch the port on in the town.

  The town check: 14 of 57 heads pass today ([must-fixes.md](must-fixes.md)).
- **Smaller notes:**
  - the grey under the jaw beneath the beard is shaded skin the beard paint doesn't cover;
  - five type-and-blink cells' lid ink rose 0.3–0.7 points;
  - §2.10's hero overrides (Cora's own file) are not built.
- **The laptop delivery** waits for the owner's go on S8.
- **The render set** needs a re-pack before the merge gate, because S7's generator files change its generator hash. Its assets are expected to be identical, as the 78 of 78 parity says.
