#!/usr/bin/env python3
"""S7's §6 cost runs (scratch): composed residents, port against main, through crowd.py's own runner.
    python3 cost.py OUT SCENARIO ARM [ARM ...]      # SCENARIO near8 | close8 | crowd64; ARM main | port | port-sb
Each arm is an asset tree (.local/char-port-2/s7/arms/<arm>) linked in as the render client's lookdev for its run; the
residents (Cullet's town, town-s6/town.json) stand composed from their person lines (LIVING_GAME_COMPOSE=1), each on
their own file as the recipe's base (the same file in every arm). `port-sb` is `port` with one woman (Runa Sarro) in
swept_braid, to price the master's own page and material. crowd.py's runner is used with its tour shot made a variable."""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

S = Path(__file__).resolve().parent
BW = Path("/home/carlid/.t3/worktrees/slop-art-online/s7-bind-client")
TOWN = Path("/home/carlid/.t3/worktrees/slop-art-online/t3-b749c655-2e53274b9e364084/.local/rs/town-s6")
MAINLD = Path("/home/carlid/.t3/worktrees/slop-art-online/t3-3fb95567-51da5b50b200809d/living/game/assets/lookdev")
BIN = str(S / "living-game-ortho")
NEAR8 = ["runa-sarro", "tamsin-hollin", "aldous-quill", "kenji-sato", "greta-dunmore", "halvard-dunmore", "lumi-pontil", "edda-hollin"]
SCEN = dict(near8=dict(count=8, size="1600x900", shot="0:58:9.43:42"), close8=dict(count=8, size="3840x2160", shot="close"), crowd64=dict(count=64, size="1600x900", shot="default"))

src = (BW / "living/tools/characters/crowd.py").read_text()
src = src.replace('LIVING_GAME_TOUR_SHOTS=",".join(["default"] * 400)', 'LIVING_GAME_TOUR_SHOTS=",".join([os.environ.get("COST_SHOT", "default")] * 400)')
src = src.replace('LIVING_GAME_TOUR_SHOTS="default", LIVING_GAME_PERF=""', 'LIVING_GAME_TOUR_SHOTS=os.environ.get("COST_SHOT", "default"), LIVING_GAME_PERF=""')
crowd = types.ModuleType("crowd")
crowd.__file__ = str(BW / "living/tools/characters/crowd.py")
sys.path[:0] = [str(BW / "living/tools/characters"), str(BW / "living/tools")]
exec(compile(src, crowd.__file__, "exec"), crowd.__dict__)


def link(arm):
    ld = BW / "living/game/assets/lookdev"
    if ld.is_symlink():
        ld.unlink()
    ld.symlink_to(S / "arms" / arm)


def prepare(arm, people):
    """The residents' own files and params in the arm's tree (links to the built ones); port-sb's Runa in swept_braid."""
    d = S / "arms" / arm
    for p in people:
        for f in (f"own-{p['name']}.glb", f"own-{p['name']}.params.json"):
            t = d / f
            if t.exists() or t.is_symlink():
                t.unlink()
            if arm == "port-sb" and p["name"] == "runa-sarro" and f.endswith(".params.json"):
                j = json.loads((MAINLD / f).read_text())
                j["person"]["styles"]["hair"] = "swept_braid"
                t.write_text(json.dumps(j))
            else:
                t.symlink_to(MAINLD / f)


def governor():
    try:
        return Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    except OSError:
        return "?"


def main():
    out, scen, arms = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
    sc = SCEN[scen]
    people = json.load(open(TOWN / "town.json"))["people"]
    if scen != "crowd64":
        people = [p for p in people if p["name"] in NEAR8]
    out.mkdir(parents=True, exist_ok=True)
    keep = os.readlink(BW / "living/game/assets/lookdev")
    original = open(crowd.RECIPES).read()
    res = []
    try:
        for i, arm in enumerate(arms):
            prepare(arm, people)
            link(arm)
            book = json.loads(original)
            crowd.town_book(book, people, "", sc["count"])
            with open(crowd.RECIPES, "w") as f:
                json.dump(book, f)
            os.environ["COST_SHOT"] = sc["shot"]
            load = open("/proc/loadavg").read().split()[0]
            r = crowd.run_game(str(out), f"{scen}-{i:02d}-{arm}", dict(LIVING_GAME_CROWD=f"{sc['count']}:1", LIVING_GAME_COMPOSE="1"), 24, sc["size"], "meadow", i < 3, BIN)
            r.update(arm=arm, scenario=scen, governor=governor(), load_before=float(load), shot=sc["shot"], size=sc["size"], count=sc["count"])
            res.append(r)
            print(json.dumps({k: r.get(k) for k in ("run", "arm", "frame_ms", "interval_ms_p50", "interval_ms_p95", "composed", "characters", "people_materials", "main_materials", "toon_materials", "main_meshes", "people_ktris", "gpu_texture_mib", "governor", "load_before")}), flush=True)
    finally:
        with open(crowd.RECIPES, "w") as f:
            f.write(original)
        ld = BW / "living/game/assets/lookdev"
        ld.unlink()
        ld.symlink_to(keep)
    (out / f"{scen}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
