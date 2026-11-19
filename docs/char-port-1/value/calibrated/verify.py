"""Repeat both sample gates from native pixels and check the published CSV."""
import csv
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from check import GRASS_MIN, LAYER_MIN, measure


def main():
    with (HERE / "sample.csv").open() as f:
        rows = list(csv.DictReader(f))
    fresh = [r for r in rows if r["fresh"] == "True"]
    retries = [r for r in rows if r["previous_failure"]]
    with (HERE.parent / "sample" / "sample.csv").open() as f:
        failed = {r["key"] for r in csv.DictReader(f)
                  if float(r["figure_ratio"]) < GRASS_MIN or float(r["layer_ratio"]) < LAYER_MIN}
    if len({r["key"] for r in fresh}) != 30 or {r["previous_failure"] for r in retries} != failed:
        raise SystemExit("Sample membership differs from the proof")
    for row in rows:
        key = row["key"]
        scores = measure(HERE / f"{key}.png")
        for field in ("figure_ratio", "layer_ratio"):
            if scores[field] is None or not math.isclose(scores[field], float(row[field]), abs_tol=1e-9):
                raise SystemExit(f"{key}: {field} differs from the measured crop")
        if scores["figure_ratio"] < GRASS_MIN or scores["layer_ratio"] < LAYER_MIN:
            raise SystemExit(f"{key} fails a native-pixel contrast gate")
    for name, group in (("Fresh", fresh), ("Prior failures", retries)):
        for field in ("layer_ratio", "figure_ratio"):
            values = [float(r[field]) for r in group]
            print(f"{name} {field}: mean {statistics.mean(values):.3f}, minimum {min(values):.3f}")


if __name__ == "__main__":
    main()
