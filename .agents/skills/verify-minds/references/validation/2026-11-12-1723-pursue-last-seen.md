# verify-minds: pursue-last-seen

## 2026-11-12 pursue-last-seen (Spark, fake model, trial server)

A mind's graph leaf for `flee`, `goto` someone or an approach now keeps running while its target is out of sight, as the intents' did.

- `roundtrip`, `acts`, `intents`: pass (`minds-pls-20261112-171134`).
- `fast-lane`: failed once ("2 fast requests inside the 6 s gap"), passed on the rerun (`minds-pls2-*`); main passed once.
- **`animals`: fails on this branch, 0 of 4** (`minds-pls-*`, `minds-pls2-*`, `minds-an-branch-173647`, `minds-an3-branch-180202` failed; `minds-an3-branch-180535`, run with a changed driver since reverted, passed). **Main 2 of 3** with the shipped driver (`minds-main-20261112-171808`, `minds-an-main-173215` passed; `minds-an-main-173050` failed). Two races in the case, seen on both builds:
  - a deer outside the case's three, living by instinct, asks one of them "to start a family"; that member thinks first and the lead takes its pick as a pack decision (`timed out waiting for a chosen option`): 2 of 3 branch failures, the one main failure;
  - a member's held "Nothing in my current plan works (flee: no #1 in sight)" (its one-step flight is over) matures about 240 s after its pack install, the moment the case asks the lead again, and the case counts that member's call as the lead's (`nothing new: no call`).
  A deer fleeing a still person with the pack's one-leaf graph behaves the same on both builds (`deerflee.py`: 4.5 → 14.6 m, the same "Nothing in my current plan works" request). Holding every other deer on `wait` and counting only the lead's calls made the case fail on main too, in a third way, so those driver changes were reverted. Unresolved: why the suitor race came up in 3 of 4 branch runs against 1 of 3 on main. `animals` is not in the scene gate.
