#!/usr/bin/env python3
"""Known answers for reflex.py's pairing (NPC-MEASURE): synthetic fighter rows with latencies set by hand."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reflex import pairs  # noqa: E402

codes = {"strike": 10, "attack": 1, "dodge": 4, "block": 2, "heal": 5, "jump": 7}
rows = [
    # (local_us, id, act, act_ms, release_ms, until_ms, target)
    (1_000_000, 8, 1, 1000, 1600, 2000, 4),   # windup at 4 (4 % 4 = 0): answered by 4's dodge at 1120 -> 120
    (1_000_100, 8, 1, 1000, 1600, 2000, 4),   # the same windup again (an update): counted once
    (1_001_000, 4, 4, 1120, 1120, 1500, 0),   # 4 dodges
    (1_002_000, 9, 10, 3000, 3500, 3900, 5),  # windup at 5 (5 % 4 = 1): answered by 5's block at 3380 -> 380
    (1_003_000, 5, 2, 3380, 3380, 4000, 9),   # 5 blocks (a guard aims at its attacker; not a windup)
    (1_004_000, 9, 10, 5000, 5500, 5900, 6),  # windup at 6 (6 % 4 = 2): never answered
    (1_005_000, 6, 4, 5600, 5600, 6000, 0),   # 6 dodges after the release: not an answer
    (1_006_000, 7, 1, 7000, 7600, 8000, 4),   # windup at 4: answered at 7000 exactly -> 0
    (1_006_500, 4, 2, 7000, 7000, 7500, 7),
    (1_007_000, 3, 5, 8000, 8400, 8600, 4),   # a heal aimed at 4: not a windup
    (9_000_000, 8, 1, 9000, 9600, 9900, 4),   # outside the window
    (9_000_100, 4, 4, 9050, 9050, 9400, 0),
]
ok = True
def check(name, got, want):
    global ok
    good = got == want
    ok &= good
    print(("PASS" if good else "FAIL"), name, got, "want", want)

lat, n = pairs(rows, codes, 4, (0, 5))
check("all fighters: latencies", lat, [0, 120, 380])
check("all fighters: windups", n, 4)
lat, n = pairs(rows, codes, 1, (0, 5))
check("share 1 (id % 4 < 1): latencies", lat, [0, 120])
check("share 1: windups", n, 2)
lat, n = pairs(rows, codes, 4, None)
check("no window: the late pair counts", lat, [0, 50, 120, 380])
sys.exit(0 if ok else 1)
