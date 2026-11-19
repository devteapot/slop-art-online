# verify-client: attention-cues

Moved from `references/validation.md` by `latest_validation.py --split`.

## 2026-11-12 attention-cues: the `cue` table and `mind_update` with cues (Spark)

After merging main `c67bb6e1` (move-intents, births-2-prep, fix-unseen-killer-id): `client-cuesm-071859` 43/43 (main's 42 and the cue check).

Branch `attention-cues` (origin/main `49dfc2cd` merged), the trial service, `scoped`. `client-cuesf-064543`: 43/43 PASS (before the merge `client-cues-061552`: 43/43). `cue` is in `PRIVATE` and refused to anonymous and player identities over WebSocket and HTTP SQL (`visibility.json`, 79 tables); the permission matrix (229 calls, 0 mismatches) sends `mind_update` with a cue, refused for another's character and for anonymous; for a player's own character it succeeds and keeps no cue (`cues-owner.json`: 0 rows on the three played characters). The probe's owner snapshot carries `cues`.
