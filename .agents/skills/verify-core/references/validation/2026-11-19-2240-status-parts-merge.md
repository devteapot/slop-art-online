# status-parts merged with main 84b7c8be

Follows [the status-parts record](2026-11-19-2215-status-parts.md). Branch `status-parts` at 6e0f57fe: origin/main 84b7c8be (doing-renew, law-override, the near-tier and cue-transport laws, scenes-token-redact, store-cred-scrub, verify-ui) merged in. The two conflicts were list neighbours, and both sides were kept: `law_about`'s entries in `skills.rhai`, and the battle-scale row of features/README.md (main had moved the body-sex row). The diff against main touches only this branch's 27 files.

Scenes ran on a private scratch server, `sao-statusparts-func2` (`clockworklabs/spacetime:v2.14.1`, 127.0.0.1:3419), not the trial server; no mind service, no model calls.

## Law override

`status_parts` and `status_parts_check` stay full-install laws, not `VALUE_ONLY`. The authority reads them only through `common::laws(ctx)`, and an alarm cell holds the way it was asked, so a value-only edit would be safe for the authority. But main's source guard (`value_only_in`) counts every whole-word occurrence of a law name outside `laws`/`law_about`, and `status_parts` is also the name of the script's `fn status_parts()` declaration. Making it value-only would mean renaming the approved law; that is left to a later change.

## Checks

- `just living-check` passed all nine steps (504 s); rules 358 passed, 17 ignored, including the 18 `script::body` tests and main's law-override tests.
- `core-spm-232727` (world seed): `alarms` 6/6; `cheap_alarms` 3/3 (18,906 kept alarm answers checked, 0 differed); `status_parts` 7/7 (9,477 asks compared, 0 differed, no error line, all 23 statuses; part memo 74,415 against 1,401 runs; with the law off, 2,798 asks all whole).
- `player-spm-232727`: verify-player `status.py` 6/6.
- Every doctor showed ticks advancing; cleanup paused and deleted both databases.

Evidence: `.local/living/verify/{core-spm-232727,player-spm-232727}/`, in `~/slop-evidence/status-parts-merge-2026-11-19.tar.zst`.

## Not covered

The A/B was not repeated on the merged head; main's additions do not touch the status path.
