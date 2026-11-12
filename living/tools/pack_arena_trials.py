#!/usr/bin/env python3
"""Writes the pack arena trial files (living/trials/pack-*.json; docs/PACK_MIND.md §5.1, §5.6): run from the repository root."""
import json, math, itertools, sys
from pathlib import Path
T=Path('living/trials')
people_spread=[[0,0],[1.5,0.8],[0,1.6],[1.5,-0.8],[0,-1.6],[3,0]]
close=[[-9,0],[-9,1.5],[-10.5,0.8],[-9,-1.5],[-10.5,-0.8],[-12,0]]
def polar(rt): return [[round(r*math.cos(math.radians(t)),1), round(r*math.sin(math.radians(t)),1)] for r,t in rt]
spread={3: polar([(15,180),(25,155),(35,205)]), 6: polar([(15,180),(20,150),(25,210),(30,170),(35,195),(28,138)])}
base={
 "title":"Pack arena (docs/PACK_MIND.md §5)",
 "about":"A wolf pack and a group of people set down near each other in open country on the island, each living by its graph; the island's other wolves (and, outside the mixed arm, its deer) are moved to the settlement farthest from the arena and kept still. Measured by living/tools/pack_arena.py. Nothing learned here is kept: the world is deleted after the evidence is taken.",
 "world":{"seed":"island"},
 "minutes":10,
 "life":{"stop_on_death":False},
 "end":{"side_down":["subject","pack"],"after_s":20},
 "record":{"bodies":{"hz":5},"uses":True},
 "variants":["instinct"],
}
def arm(name, wolves, people, start, night=False, wolf_graph="instinct:wolf_bold", deer=False, about=None, minds=None, people_graph="instinct:person"):
    t=json.loads(json.dumps(base))
    if minds:
        # Both sides think (docs/PACK_MIND.md §6 steps 5-6): every person and wolf of the arena.
        t["minds"]={"roles":minds,"concurrency":16}
        t["variants"]=["pack-minds"]
        t["record"]["thoughts"]=True
        t["record"]["experiences"]=True
    t["arena"]={"people":"subject","wolves":"pack","night":night,"start":start,"deer":deer}
    t["subject"]={"pick":{"kind":"person","stage":2,"count":people,"bg":{"town":"Brackenford"}},"clear_items":True,"clear_routines":True}
    t["cast"]={"pack":{"pick":{"kind":"wolf","stage":2,"count":wolves,"nearest":{"arrival":True}}},
               "spare_wolves":{"pick":{"kind":"wolf","count":"all"}}}
    steps=[{"do":"graph","who":"spare_wolves","graph":{"wait":900}},
           {"do":"place","who":"spare_wolves","to":{"farthest_town":{"who":"pack"}}}]
    if not deer:
        t["cast"]["deer"]={"pick":{"kind":"deer","count":"all"}}
        steps+=[{"do":"graph","who":"deer","graph":{"wait":900}},
                {"do":"place","who":"deer","to":{"farthest_town":{"who":"pack"},"offset":[0,6]}}]
    if night: t["world"]={"seed":"island","start_hour":21}
    wolf_off = close if start=="close" else spread[wolves]
    steps+=[
        {"do":"graph","who":"subject","graph":people_graph},
        {"do":"graph","who":"pack","graph":{"wait":5}},
        {"do":"background","who":"pack","background":{"pack":"the arena pack","bold":True}},
        {"do":"place","who":"subject","to":{"who":"pack","offset":[9,0],"spread":people_spread}},
        {"do":"place","who":"pack","to":{"who":"subject","spread":wolf_off},"after":1},
        ({"do":"graph","who":"pack","graphs":wolf_graph,"after":1} if isinstance(wolf_graph,list) else {"do":"graph","who":"pack","graph":wolf_graph,"after":1})]
    t["timeline"]=[{"at":"start","steps":steps}]
    t["title"]=f"Pack arena: {wolves} wolves v {people} people, {start} start{', night' if night else ''}{', with deer' if deer else ''}"
    if about: t["about"]=about
    (T/f"{name}.json").write_text(json.dumps(t,indent=1)+"\n")
    return t
FLEE={"if":{"cond":{"all":[{"hurt_within":8},{"health":{"below":20}}]},"then":{"do":{"skill":"flee","target":"attacker"}}}}
BITE={"if":{"cond":{"all":[{"near":{"target":{"nearest":"person"},"within":3.5}},{"chance":0.3}]},"then":{"do":{"skill":"attack","target":{"nearest":"person"}}}}}
def sides(side): return {"first":[FLEE,BITE,{"do":{"skill":"circle","target":{"nearest":"person"},"radius":4,"side":side}}]}
C1=[sides("left"),sides("right")]
C2={"first":[FLEE,
  {"if":{"cond":{"all":[{"near":{"target":{"nearest":"wolf"},"within":3}},{"near":{"target":{"nearest":"person"},"within":6}}]},"then":{"do":{"skill":"back_off","target":{"nearest":"wolf"},"distance":4}}}},
  BITE,
  {"do":{"skill":"keep_distance","target":{"nearest":"person"},"min":3,"max":5}}]}
def running(g):
    """The fixture with every movement intent at a run (the first fixtures walked, 3.4 m/s,
    after people fleeing at a run: no ring could form; docs/PACK_MIND.md §7)."""
    if isinstance(g, list):
        return [running(x) for x in g]
    if isinstance(g, dict):
        out = {k: running(v) for k, v in g.items()}
        if out.get("skill") in ("circle", "keep_distance", "back_off", "close_in"):
            out["run"] = True
        return out
    return g
C1R=running(C1)
C2R=running(C2)
CAL_ABOUT="Calibration fixture (docs/PACK_MIND.md §5.6): graphs written by us, kept in this trial file only, never shipped; they measure whether the world lets wolves ring a person, not whether wolves do."
if __name__=="__main__":
    for start in ("close","spread"):
        for w,p in ((3,3),(6,3),(3,6),(6,6)):
            arm(f"pack-{start}-{w}v{p}", w, p, start)
    arm("pack-spread-6v6-night", 6, 6, "spread", night=True)
    for start in ("close","spread"):
        arm(f"pack-minds-{start}-6v6", 6, 6, start, minds=["subject","pack"],
            about="Both sides with minds (wolves LIVING_ANIMAL_MINDS=salient,choose; people the default mix), starting from their instinct graphs; nothing in any prompt names a tactic (docs/PACK_MIND.md §5.5 guards).")
    arm("pack-minds-mixed-6v6", 6, 6, "spread", deer=True, minds=["subject","pack"],
        about="Both sides with minds, the island's deer left where they live (the mixed arm).")
    for name,gr in (("c1r",C1R),("c2r",C2R)):
        for start,w,pp in (("close",3,3),("close",6,6)):
            arm(f"pack-{name}-{start}-{w}v{pp}", w, pp, start, wolf_graph=gr, about=CAL_ABOUT)
        arm(f"pack-{name}-stand-6v6", 6, 6, "close", wolf_graph=gr, people_graph={"wait":900},
            about=CAL_ABOUT+" The people stand where they are (they hold their ground and do not strike): the plainest test of whether wolves can ring a target.")
    for name,g in (("c1",C1),("c2",C2)):
        for start,w,pp in (("close",3,3),("close",6,6),("spread",6,6)):
            arm(f"pack-{name}-{start}-{w}v{pp}", w, pp, start, wolf_graph=g, about=CAL_ABOUT)
