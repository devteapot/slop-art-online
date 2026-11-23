# char-port-2 · S7 · §6 cost

**What was run:** port against main, with Cullet's residents composed from their person lines (`LIVING_GAME_COMPOSE=1`), as the game draws people. Each run is 24 s, uncapped, in a fresh process, on the dev-box, 2026-11-23 09:58–10:14. The CPU governor was `performance` on every run, so these timings compare only with runs after the 2026-11-22 12:25 switch.

**The arms** (each an asset tree linked in as the client's lookdev; the client is the dev-box's S7 build, main with hair-mirror and view-ortho):
- **main:** the render set 61421f56f964, main's shipped assets.
- **port:** S7's final types, overlays and hair set (`swept_braid` on its own page) over the same render set, with every resident in their own style.
- **port-sb:** port with one resident woman (Runa Sarro) in `swept_braid`. No resident draws the master under the current pool rule, so this arm prices its own page and material (decision 1).

**The scenarios:**
- **8 near:** eight residents of the classes, at the Near stop (`0:58:9.43:42`), 1600×900.
- **8 close:** the same eight at the 4K close shot.
- **64 crowd:** the 64 residents at the game camera, 1600×900.

Each scenario ran the arms rotated three times (port, main, port-sb; main, port-sb, port; port-sb, port, main). The medians over each arm's three runs:

| Scenario | Limit | main | port | port-sb | **port − main** | **page alone (port-sb − port)** | port-sb − main |
|---|---|---|---|---|---|---|---|
| 8 near, 1600×900 | +0.3 ms | 3.62 ms | 3.69 ms | 3.67 ms | **+0.07 ms** | −0.02 ms | +0.05 ms |
| 8 close, 4K | +0.3 ms | 7.14 ms | 7.26 ms | 7.22 ms | **+0.12 ms** | −0.04 ms | +0.08 ms |
| 64 crowd, 1600×900 | +1.0 ms | 5.41 ms | 5.48 ms | 5.56 ms | **+0.07 ms** | +0.08 ms | +0.15 ms |

**Draw counts** (the people's mesh-material pairs and materials, from the client's own diagnostics):

| Scenario | main pairs / materials | port | port-sb |
|---|---|---|---|
| 8 near | 33 / 25 | 34 / 27 | 34 / 27 |
| 8 close | 117 / 48 | 124 / 52 | 124 / 53 |
| 64 crowd | 103 / 24 | 103 / 26 | 104 / 27 |

**What it says:**
- **The port is within every limit:** +0.07 ms at 8 near (limit +0.3), +0.12 ms at the 4K close (+0.3), +0.07 ms on the 64-crowd (+1.0). It adds two materials, the overlays and the beard's own, and up to 7 pairs at the close shot.
- **`swept_braid`'s own page passes.** It adds one material and one mesh-material pair where it is drawn (the crowd and the close shot), and +0.08 ms on the 64-crowd, within the run-to-run spread. At the Near stop it added nothing measurable.
- **The run-to-run spread** is up to 0.3 ms on the crowd (main's three runs: 5.71, 5.39, 5.41 ms), so differences under about 0.1 ms are noise. The one-minute load before each run was 1.8–8.8; the runs follow one another, so that figure includes the previous run's own load.
- **Not compared: GPU texture memory.** The port tree's textures are PNG and the render set's are KTX2, so they aren't like for like (port 532 MiB against main 203 MiB at 8 near). The bundle packs both in KTX2.

**Files:**
- per-run results: `near8.json`, `close8.json`, `crowd64.json`;
- the medians and differences: `table.json`;
- the harness and the table: `cost.py` and `cost_table.py`, which use `crowd.py`'s own runner.
