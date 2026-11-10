#!/usr/bin/env python3
"""Cache positions of things an act failed at (#N) for each instance of a batch, while its
databases exist (docs/MIND_FEEDBACK.md): feedback_idpos.py <evidence batch dir> <container> -> <dir>/idpos.json"""
import json, re, subprocess, sys, glob, os
bdir, container = sys.argv[1], sys.argv[2]
out = os.path.join(bdir, "idpos.json")
cache = json.load(open(out)) if os.path.exists(out) else {}
for inst in sorted(glob.glob(os.path.join(bdir, "*-r*"))):
    name = os.path.basename(inst); db = f"verify-trial-{os.path.basename(bdir)}-{name}"
    ids = set()
    try:
        for l in open(os.path.join(inst, "experiences.jsonl"), errors="replace"):
            for m in re.finditer(r"(?:→|\\u2192) #(\d+)", l):
                ids.add(m.group(1))
    except FileNotFoundError:
        continue
    have = cache.setdefault(name, {})
    for i in sorted(ids - set(have)):
        row = {}
        for table, cols in (("structure", "id, kind, x, y"), ("resource_node", "id, kind, x, y")):
            r = subprocess.run(["docker", "exec", container, "spacetime", "sql", "-s", "local", db, f"SELECT {cols} FROM {table} WHERE id = {i}"], capture_output=True, text=True)
            lines = [x for x in r.stdout.splitlines() if "|" in x][1:]
            if lines:
                p = [x.strip().strip('"') for x in lines[0].split("|")]
                row[table] = {"kind": p[1], "x": float(p[2]), "y": float(p[3])}
        r = subprocess.run(["docker", "exec", container, "spacetime", "sql", "-s", "local", db, f"SELECT id, kind FROM character WHERE id = {i}"], capture_output=True, text=True)
        if r.returncode == 0 and len([x for x in r.stdout.splitlines() if "|" in x]) > 1:
            row["character"] = True
        if r.returncode != 0 and "not found" in (r.stderr + r.stdout).lower():
            continue
        have[i] = row
json.dump(cache, open(out, "w"), indent=1)
