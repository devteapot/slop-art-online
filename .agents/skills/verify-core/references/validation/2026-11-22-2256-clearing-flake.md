# The clearing check's staging (`clearing-flake`): the core surface

Validated on the dev-box on branch `clearing-flake` from `origin/main` `73e823313`. Server `mc-stdb` (private, `127.0.0.1:3390`, `clockworklabs/spacetime:v2.14.1`); `performance` governor. No paid model calls. Test-only: `living/tools/verify_mechanics.py` (`ground_spot`, `terrain_under`, `clear_ready`; `plant_spot` now uses `ground_spot`) and [features/mechanics.md](../../features/mechanics.md), "Clearing from the forest's edge". The driver's 23 checks, their names and the reducers it calls are unchanged.

## The failure

`wolves-scene`'s scene gate (batch 59, `gate-1122224047-489894-a-mechanics`) failed "clearing forest yields wood": D's last line was "You failed to clear: there is no forest to clear where you stand", with an empty pack after 150 s. The rerun passed, but no flake is recorded for this check, so the gate stopped.

## The cause

The old sequence was: the nearest tree by straight line, then `goto {nearest: forest}`, then `clear`.
- A goto reports its arrival when its final approach begins (`motion::FLAG_EARLY`), so the clear could start on the grass beside the forest.
- The nearest tree could be across water.

## Probe runs (`.local/mc/`, default seed)

| Round | World | Staging | Runs | Result |
|---|---|---|---|---|
| `c4` | `verify-clr-4` | old | 50 | 48 cleared. 3 first clears failed "no forest to clear where you stand", each with the walker sampled on grass with the clear under way, then retried and cleared. 2 never cleared: from the same beach the tree was across water, and every retry failed "no path there". |
| `f3` | `verify-clr-3` | fixed | 60 | 60 cleared, 60 standing on forest before the clear, no clear refused. |

**Not counted:**
- `c1` and `c2` (`verify-clr-1`, `verify-clr-2`) counted feedback lines carried over from a walker's earlier runs.
- `c2` also reused walkers until they were exhausted.
- `c1` ran on after the world's inactivity lease paused it (round 10 on).
- The `c1` trace of a 115 s walk round water stands.

**Not reproduced:** a first clear failure that never recovered within 150 s, as in the gate.

## The fixed driver, as the gate drives it

`verify.py launch --seed world`, then `verify_mechanics.py --gate-world`, then cleanup. Fresh worlds, 4 at a time, 2 rounds:

| Run | Result | Clearing staging |
|---|---|---|
| `gate-cf1-1-mechanics` | 23/23 | walks 3.0 m |
| `gate-cf1-2-mechanics` | 23/23 | walks 17.0 m |
| `gate-cf1-3-mechanics` | 23/23 | walks 5.7 m |
| `gate-cf1-4-mechanics` | 23/23 | walks 9.2 m |
| `gate-cf2-1-mechanics` | 23/23 | placed: no forest in a straight walk within 20 m |
| `gate-cf2-2-mechanics` | 23/23 | walks 0.0 m |
| `gate-cf2-3-mechanics` | 23/23 | walks 4.0 m |
| `gate-cf2-4-mechanics` | 23/23 | walks 3.6 m |

Evidence: `.local/mc/` (`clear_probe.py`, `fixed_probe.py`, `proof.sh`, the logs and JSON lines) and `.local/living/verify/{clr-1..4,gate-cf*-mechanics}/`, archived to `~/archive/worktree-evidence-20261122/clearing-flake.tar.zst`.

## Not covered

- The other checks were exercised only within the 8 full driver runs.
- The engine's early arrival also reaches any graph that chains a `goto` with a skill that reads the ground underfoot. This record does not judge that; the fixture no longer depends on it.
