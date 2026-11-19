# doing-renew, pacing-neutral: cue timing, quiet and busy (verify-client)

This follows [2026-11-19-1955-doing-renew](2026-11-19-1955-doing-renew.md), where the first design had late windups on a crowded container. Branch `doing-renew` at `67527f4c` (the `doing` row held until the next evaluation; nothing begins sooner), main `440ca6a7`. Server: the worker's own `slop-doingrenew-stdb` (v2.14.1). `cues.py` was run alone on fresh worlds, alternating branch and main.

## Runs

- **Quiet** (one world on the container, host load about 7): every `cues.py` run 21/21.
  - Branch `client-hq1`: windups 19–32 ms by cue, law off 18–45 ms.
  - Main `client-mq1`: 18–48 ms, law off 7–34 ms.
  - Branch `client-hq2`: 6–40 ms, law off 23–36 ms.
- **Busy** (three realm-4 worlds of about 190 residents ticking beside it on the same container, host load 10–12): every `cues.py` run 21/21.
  - Branch `client-hb1`: 10–21 ms, law off 43–54 ms.
  - Main `client-mb1`: 24–36 ms, law off 23–46 ms.
  - Branch `client-hb2`: 20–39 ms, law off 24–77 ms.
  - Main `client-mb2`: 12–36 ms, law off 40–53 ms.

No late windup on either build. The probe and the suite are as in the first record (`client-renew8`, 45/0), and no table, view or reducer changed since.

Evidence (worktree, not in git): `.local/living/verify/client-hq1/`, `client-hq2/`, `client-hb1/`, `client-hb2/`; main's `~/slop-doingrenew-target/main-wt/.local/living/verify/client-mq1/`, `client-mb1/`, `client-mb2/`; archived in `~/slop-evidence/doing-renew-hold-20261119.tar.zst`.
