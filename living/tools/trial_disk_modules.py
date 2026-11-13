#!/usr/bin/env python3
"""Add each archived commitlog's module to the evidence (docs/TRIAL_DISK.md): a commitlog decodes
only with the module that wrote it. The run's actions.log names the served file
(`<module>-wt<hash>.wasm`); the exact served copy is preferred (the trial server's /wasm mount,
~/dev/slop-trials/.local/living/trials/wasm), then the checkout's own build of the base name.
Usage: trial_disk_modules.py LIST.json EVIDENCE_DIR"""
import hashlib, json, re, sys
from pathlib import Path

lst, ev = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
served = Path.home() / "dev/slop-trials/.local/living/trials/wasm"
man = [json.loads(l) for l in (ev / "MANIFEST.jsonl").read_text().splitlines()]
by = {x["replica"]: x for x in lst}
done = {}
out = ev / "MODULES.jsonl"
for m in man:
    x = by.get(m["replica"]) or {}
    mod, root = x.get("module"), x.get("root")
    if not mod:
        continue
    key = (m["batch"], mod)
    if key in done:
        continue
    base = re.sub(r"-wt[0-9a-f]{6}$", "", mod)
    cands = [(served / f"{mod}.wasm", "served copy (exact name)")]
    if root:
        cands += [(Path(root).parent / "wasm" / f"{mod}.wasm", "checkout (exact name)"), (Path(root).parent / "wasm" / f"{base}.wasm", "checkout build of the base name")]
    src = next(((p, how) for p, how in cands if p.exists()), None)
    rec = {"batch": m["batch"], "module": mod, "source": None, "how": None, "sha256": None}
    if src:
        dest = ev / m["batch"] / f"{mod}.wasm"
        dest.write_bytes(src[0].read_bytes())
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        with open(ev / "SHA256SUMS", "a") as f:
            f.write(f"{h}  {m['batch']}/{mod}.wasm\n")
        rec.update(source=str(src[0]).replace(str(Path.home()), "~"), how=src[1], sha256=h)
    done[key] = rec
    with open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")
miss = [r for r in done.values() if not r["source"]]
print(f"{len(done)} modules for {len({k[0] for k in done})} batches; {len(miss)} not found: {[(r['batch'], r['module']) for r in miss][:10]}")
