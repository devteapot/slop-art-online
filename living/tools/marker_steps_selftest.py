#!/usr/bin/env python3
"""Known answers for marker_steps.py: fake ticks with known µs starts give the known p99 and share."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_steps import intervals, summary  # noqa: E402

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok &= good
    print("PASS" if good else "FAIL", name, got, "want", want)


def ticks(gaps, start=1_000_000_000):
    """Ticks 1.. with the given intervals (µs) between consecutive starts."""
    out, t = [(1, start)], start
    for i, g in enumerate(gaps, 2):
        t += g
        out.append((i, t))
    return out


# 999 intervals: 984 of 16,667 µs and 15 of 30,000. Sorted, index int(0.99 * 999) = 989 is a long one.
gaps = [16_667] * 984 + [30_000] * 15
iv, n = intervals(ticks(gaps), 0, 10**18)
s = summary(iv, 60.0, n)
check("15 long of 999: p99", s["p99_ms"], 30.0)
check("15 long of 999: over 25", s["over25_pct"], round(100 * 15 / 999, 3))
check("15 long of 999: p50", s["p50_ms"], 16.667)
check("15 long of 999: fails the line", s["pass"], False)
# 5 long of 999: index 989 is a short one; 0.5% over 25 is the bound, and 5/999 = 0.501% is over it.
iv, n = intervals(ticks([16_667] * 994 + [30_000] * 5), 0, 10**18)
s = summary(iv, 60.0, n)
check("5 long of 999: p99", s["p99_ms"], 16.667)
check("5 long of 999: over 25", s["over25_pct"], 0.501)
check("5 long of 999: fails on the share", s["pass"], False)
# 4 long of 999 at 17.4 ms ticks: passes.
iv, n = intervals(ticks([17_400] * 995 + [26_000] * 4), 0, 10**18)
check("4 long of 999, 17.4 ms steps: passes", summary(iv, 59.95, n)["pass"], True)
check("the same, 59.8 ticks/s: fails", summary(iv, 59.8, n)["pass"], False)
# A duplicate line counts once, a missing tick breaks the chain, the window cuts.
lines = [(1, 0), (1, 5), (2, 16_000), (3, 33_000), (5, 70_000), (6, 86_000), (7, 999_000)]
iv, n = intervals(lines, 0, 100_000)
check("duplicates, a gap, the window: intervals", iv, [16.0, 16.0, 17.0])
check("duplicates, a gap, the window: ticks counted", n, 5)
# The idle clause: the bound is max(17.5, idle p99 + 0.5).
from marker_steps import p99_bound  # noqa: E402
check("idle 18.08: bound", p99_bound(18.08), 18.58)
check("idle 17.0: bound", p99_bound(17.0), 17.5)
check("no idle run: bound", p99_bound(None), 17.5)
iv, n = intervals(ticks([16_667] * 980 + [18_300] * 19), 0, 10**18)
check("p99 18.3 ms: fails without the idle clause", summary(iv, 59.95, n)["pass"], False)
check("p99 18.3 ms, idle 18.08: passes", summary(iv, 59.95, n, 18.08)["pass"], True)
check("p99 18.3 ms, idle 17.0: fails", summary(iv, 59.95, n, 17.0)["pass"], False)
sys.exit(0 if ok else 1)
