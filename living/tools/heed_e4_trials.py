#!/usr/bin/env python3
"""Writes E4's arena trial files, its variants and its fake script (docs/ATTENTION_E4.md;
docs/ATTENTION_BUDGET.md v2 §8.2). Run from the repository root.

The fixture is the pack arena (docs/PACK_MIND.md §5): six bold wolves on their shipped
instinct against six adult people of Brackenford, spread start, by day and at night. The
people carry a spear and fight on `spawn_battle`'s combat graph aimed at wolves (block or
dodge, by id parity, when threatened; else attack the nearest wolf), so that whom they keep
track of decides what they meet and what they see coming. Their minds run on the fake model
(`living/trials/fake/heed-e4.json`): deliberations keep the graph (`"graph": "keep"`) and say
nothing, so the heed policy stays the instinct and the graph stays the fixture's; only capacity
varies between arms.

Arms (variants), the same trial file:
  heed-off      the law off: everyone in sight is an individual (today)
  heed-formula  heed on, the shipped `heed_capacity(a)` formula for everyone, ceiling 32
  heed-capN     heed on, the people's capacity fixed at N (4, 8, 16, 32), the wolves on the
                formula, ceiling 32
"""
import json
import math
from pathlib import Path

T = Path("living/trials")
PEOPLE_SPREAD = [[0, 0], [1.5, 0.8], [0, 1.6], [1.5, -0.8], [0, -1.6], [3, 0]]


def polar(rt):
    return [[round(r * math.cos(math.radians(t)), 1), round(r * math.sin(math.radians(t)), 1)] for r, t in rt]


WOLF_SPREAD = polar([(15, 180), (20, 150), (25, 210), (30, 170), (35, 195), (28, 138)])


def fighter(defend):
    return {"first": {"label": "combat", "children": [
        {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": defend}}}},
        {"do": {"skill": "attack", "target": {"nearest": "wolf"}}}]}}


def trial(night):
    t = {
        "title": f"E4 heed arena: 6 bold wolves v 6 people with spears, spread start{', night' if night else ''}",
        "about": "docs/ATTENTION_E4.md: the pack arena (docs/PACK_MIND.md §5) with people who fight back on spawn_battle's combat graph aimed at wolves (block or dodge when threatened, else attack the nearest wolf). Only the people's heed capacity varies between arms (variants in living/trials/heed-e4-variants.json). The island's other wolves and its deer are moved to the settlement farthest from the arena and kept still. Nothing learned here is kept: the world is deleted after the evidence is taken.",
        "world": {"seed": "island", "start_hour": 21} if night else {"seed": "island"},
        "minutes": 6,
        "life": {"stop_on_death": False},
        "end": {"side_down": ["subject", "pack"], "after_s": 20},
        "record": {"bodies": {"hz": 5}, "uses": True, "thoughts": True, "experiences": True},
        "variants": ["heed-off"],
        "minds": {"roles": ["subject"], "concurrency": 8},
        "arena": {"people": "subject", "wolves": "pack", "night": night, "start": "spread", "deer": False},
        "subject": {"pick": {"kind": "person", "stage": 2, "count": 6, "bg": {"town": "Brackenford"}}, "clear_items": True, "clear_routines": True},
        "cast": {
            "pack": {"pick": {"kind": "wolf", "stage": 2, "count": 6, "nearest": {"arrival": True}}},
            "spare_wolves": {"pick": {"kind": "wolf", "count": "all"}},
            "deer": {"pick": {"kind": "deer", "count": "all"}},
        },
        "timeline": [{"at": "start", "steps": [
            {"do": "graph", "who": "spare_wolves", "graph": {"wait": 900}},
            {"do": "place", "who": "spare_wolves", "to": {"farthest_town": {"who": "pack"}}},
            {"do": "graph", "who": "deer", "graph": {"wait": 900}},
            {"do": "place", "who": "deer", "to": {"farthest_town": {"who": "pack"}, "offset": [0, 6]}},
            {"do": "graph", "who": "subject", "graph": {"wait": 5}},
            {"do": "items", "who": "subject", "items": {"spear": 1}},
            {"do": "graph", "who": "pack", "graph": {"wait": 5}},
            {"do": "background", "who": "pack", "background": {"pack": "the arena pack", "bold": True}},
            {"do": "place", "who": "subject", "to": {"who": "pack", "offset": [9, 0], "spread": PEOPLE_SPREAD}},
            {"do": "place", "who": "pack", "to": {"who": "subject", "spread": WOLF_SPREAD}, "after": 1},
            {"do": "graph", "who": "subject", "graphs": [fighter("dodge"), fighter("block")], "after": 1},
            {"do": "graph", "who": "pack", "graph": "instinct:wolf_bold", "after": 1},
        ]}],
    }
    return t


CAP_OLD = "fn heed_capacity(a) {"


def capped(n):
    return {"people_capacity": [CAP_OLD, CAP_OLD + f"\n    if a.actor.kind == \"person\" {{ return {float(n)}; }}"]}


def variants():
    on = {"heed_on": True, "heed_ceiling": 32}
    v = {"heed-off": {"about": "E4 control: the heed law off (as shipped): everyone in sight is an individual.", "models": {}, "env": {}},
         "heed-formula": {"about": "E4: heed on, every character on the shipped heed_capacity formula, ceiling 32.", "models": {}, "env": {}, "world_laws": on}}
    for n in (4, 8, 16, 32):
        v[f"heed-cap{n}"] = {"about": f"E4: heed on, people's capacity fixed at {n} (wolves on the formula), ceiling 32.", "models": {}, "env": {}, "world_laws": on, "skills_patch": capped(n)}
    return v


FAKE = {
    "about": "E4 (docs/ATTENTION_E4.md): fake minds that keep their graph and say nothing, so the arena's people keep the fixture's combat graph and the heed instinct; only capacity varies. Deliberations answer `graph: keep`; thinks say nothing.",
    "replies": {
        "think": {"thought": "I keep to what I am doing.", "intend": [], "say": {"text": "", "to": None}, "judgments": [], "places": []},
        "deliberate": {"thought": "I keep to what I am doing.", "plan": "keep", "graph": "keep", "say": {"text": "", "to": None}, "acts": []},
    },
    "rules": [],
}


def main():
    for night in (False, True):
        name = f"heed-e4-{'night' if night else 'day'}"
        (T / f"{name}.json").write_text(json.dumps(trial(night), indent=1) + "\n")
        print("wrote", T / f"{name}.json")
    (T / "heed-e4-variants.json").write_text(json.dumps(variants(), indent=1) + "\n")
    (T / "fake/heed-e4.json").write_text(json.dumps(FAKE, indent=1) + "\n")
    print("wrote", T / "heed-e4-variants.json", T / "fake/heed-e4.json")


if __name__ == "__main__":
    main()
