# mind-act-replace: the mind's acts with the law off

`mind_act` and `mind_act_checked` now reach the act queue through `acts::submit_mind` / `submit_checked`, which replace the act in progress only under the value-only law `mind_act_replaces` (off as shipped). Private server `slop-actreplace-20261120`, main `7499c270` plus the branch, fake model.

- `minds-mar-005352`: `acts`, `dealings`, `roundtrip`, `fast-lane`, `takeover` PASS (exit 0).
- With the law on, the mind service's `mind_act_checked` path ran in the six 200-fighter `battle_diag.py` runs of docs/INPUT_LATENCY.md "Mind acts replace" (about 1,070 deliberate acts a run, every `act_submit` marker with replace 1 in the on arm); no act was decided while another ran, so none was replaced there.

Evidence: `.local/living/verify/minds-mar-005352-*` in `~/slop-evidence/mind-act-replace-20261120.tar.zst`.
