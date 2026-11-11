#!/usr/bin/env python3
"""Where a cargo build's time went, from its `--timings` report (docs/TOOLING.md).

Prints the build's wall time, the summed unit time split into workspace crates and
dependencies (with build scripts and proc-macros, which a compile cache cannot serve), and
the slowest units. Usage: check_timings.py <cargo-timing.html>... [--top N]
"""
import json
import re
import sys

WORKSPACE = {"living-rules", "living-authority", "living-bindings", "living-mind", "living-viewer", "living-game"}


def units(path):
    text = open(path, errors="replace").read()
    m = re.search(r"const UNIT_DATA = (\[.*?\n\]);", text, re.S)
    data = json.loads(m.group(1)) if m else []
    wall = re.search(r"<td>Total time:</td><td>([\d.]+)s", text)
    return data, float(wall.group(1)) if wall else max((u["start"] + u["duration"] for u in data), default=0.0)


def main(argv):
    top = 12
    if "--top" in argv:
        i = argv.index("--top")
        top = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    for path in argv:
        data, wall = units(path)
        groups = {"workspace": 0.0, "deps": 0.0, "build scripts": 0.0, "proc-macros": 0.0}
        for u in data:
            t = u["target"].strip()
            if u["name"] in WORKSPACE:
                groups["workspace"] += u["duration"]
            elif "build-script" in t:
                groups["build scripts"] += u["duration"]
            elif "proc-macro" in t or u.get("mode") == "proc-macro":
                groups["proc-macros"] += u["duration"]
            else:
                groups["deps"] += u["duration"]
        print(f"== {path}\n   wall {wall:.1f} s, {len(data)} units; unit time: " + ", ".join(f"{k} {v:.0f} s" for k, v in groups.items()))
        for u in sorted(data, key=lambda u: -u["duration"])[:top]:
            print(f"   {u['duration']:7.1f} s  {u['name']} {u['target'].strip()}")


if __name__ == "__main__":
    main(sys.argv[1:])
