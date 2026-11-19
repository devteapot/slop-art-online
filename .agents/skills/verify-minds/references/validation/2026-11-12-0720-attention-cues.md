# verify-minds: attention-cues

Moved from `references/validation.md` by `latest_validation.py --split`.

## 2026-11-12 attention-cues: a mind's cue through memory to a thought (Spark)

After merging main `c67bb6e1` (move-intents, births-2-prep): `minds-cuesm-071859` `cues_mind.py` 6/6.

Branch `attention-cues` (origin/main `49dfc2cd` merged), the trial service with `slop-trials-neo4j`, the release mind and the fake model. `cues_mind.py` (new; features/cues.md): `minds-cuesf-064543` 6/6 on the merged build (the cue projected through `mind_update` in the reply's words; a player W does not know at 3 m gives one `noticed` line; the next think request, 0.4 s after it, carries it as its reason; `# What you watch for` lists the cue as having made W think). Two earlier attempts found product bugs, fixed before the pass (`minds-cues-062519`): the compile step dropped the think decision's `notice` (`keep` now carries it), and a fire 2 s after the last thought was recorded although the authority refused the request within `think_min_s` (a fire now waits for the request to be taken: 22.8 s after the previous think here). Mind tests `cue_examples_name_no_one`, `notice_is_kept_on_what_it_serves`. The `resident` case's `mind_update` now passes `cues` (not re-run: the suite's other cases were not run on this branch).
