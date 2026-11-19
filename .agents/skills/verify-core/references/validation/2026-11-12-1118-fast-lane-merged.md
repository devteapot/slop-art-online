# verify-core: fast-lane, after merging main

Follows [2026-11-12-1054-fast-lane.md](2026-11-12-1054-fast-lane.md). Branch `fast-lane` merged with origin/main (21 commits, among them `regard_cache`, which shares the perceived labels the trigger's reasons use); the trial service `slop-trials-stdb`.

- `scenes.py seen_again` failed its last check three times (`core-seen2-121220`, `core-seen3-121507`, `core-seen4-121551`): D, the archer behind C with `fov_on` on, shot 0 or 1 times. D sees only the way it faces, and its facing had been luck in the first run. The scene now turns D toward C first; re-running `face` inside the shooting loop stalled it (1 shot), so D faces once, then shoots.
- After the fix: 8/8 twice (`core-seen5-121654`, `core-seen6-121742`). C was told only "An arrow struck you from somewhere you could not see: …", never "winds up".
- verify-minds `fast-lane` passed on the merged code (`minds-fast3-121322`); `just living-check` exit 0 (355 s).
