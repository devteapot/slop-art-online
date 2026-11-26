"""The swept_braid master's tolerance check on one person's head, with no build (char-port-2 S7, the coordinator's town
check): person.py runs up to the master's own check (hair.master_scale), which records each variation scale it tried,
its measures and the tolerances, and stops there.
    SLOP_PORT=...,hair,masters blender -b -P swept_braid_check.py -- OUT.json --params P.json --set hair.style=swept_braid \
        --parts hair --morphs client --lod near --out TMP.glb"""
import json, runpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
out, args = argv[0], argv[1:]
sys.path.insert(0, "living/tools/blender")
import hair  # noqa: E402

def master_scale(hf, spec, hairline, covered, bald, body):
    tried = []
    for scale in (1.0, 0.5, 0.25, 0.0):
        h = hair.Hair(hf, dict(spec, _vary_scale=scale), hairline, covered=covered, bald=bald, body=body, detail=1.0)
        w = bool(h.within())
        tried.append(dict(scale=scale, within=w, measures=h.measures()))
        if w:
            break
    json.dump(dict(passed=tried[-1]["within"], tried=tried, tolerance=hair.MASTERS["swept_braid"]["tolerance"]), open(out, "w"), default=float)
    raise SystemExit(0)

hair.master_scale = master_scale
sys.argv = ["person.py", "--"] + args
runpy.run_path("living/tools/blender/person.py", run_name="__main__")
