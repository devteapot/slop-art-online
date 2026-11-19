# Fast-lane issue path with the sight gather

Branch `fast-lane-frame` (commit `ba6fabec`): at every issue, `fast::pump` now also writes the asker's `fast_sight` row (`fast::sight`), and `fast::forget` removes it together with the request. Run `core-flf-102927` on the trial container passed both checks below and cleaned up (exit 0).

- `scenes.py seen_again`: the repeat trigger, with nothing issued, so no sight gather.
- `scenes.py fast_diag`: issues rows, so `sight` runs on each one. Every `fast:*` counter was above zero, and none appeared after profiling stopped.

This record does not cover the counts' values: verify-minds `fast-frame` checks those against the prompt and the scene (`2026-11-19-…-fast-lane-frame.md` there). `set_background` now writes an authored sheet's traits into the genome (`seed::author_temperament`); verify-minds `fast-frame` checks that too.

Evidence: `.local/living/verify/core-flf-102927/`.
