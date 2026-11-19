"""The battle fixture's personas (battle_diag.py; docs/FAST_LANE_FRAME.md): authored residents'
sheets from battle_personas.json, three cohorts (martial, protective, timid), drawn from the world
seed alone so that every arm of a comparison on one seed fights with the same people."""
import json
import random
from pathlib import Path

PERSONAS = json.loads((Path(__file__).resolve().parent / "battle_personas.json").read_text())["cohorts"]
COHORTS = ("martial", "protective", "timid")
# The fields an authored resident's sheet carries that a battle persona gives (seed.rs `sheet`,
# read by the mind's `sheet_persona`), and the person traits (rules genes.rs `PERSON_TRAITS`).
SHEET_FIELDS = {"narrative", "values", "goals", "mood", "traits", "pastimes", "calling"}
PERSON_TRAITS = {"caution", "sociability", "empathy", "curiosity", "ambition", "introspection", "temper", "nurture"}


def persona_mix(world_seed, n):
    """The initial fighters' personas, by formation slot: an even mix of the cohorts (as even
    as n allows), shuffled and given a sheet each from the world seed alone, so every arm of a
    comparison on one seed has the same fighters as the same people. -> [(cohort, index)]"""
    rng = random.Random(f"battle personas {world_seed}")
    kinds = [COHORTS[i % len(COHORTS)] for i in range(n)]
    rng.shuffle(kinds)
    return [(k, rng.randrange(len(PERSONAS[k]))) for k in kinds]


def refill_personas(world_seed):
    """The refills' personas in the order refills are made, from their own seeded stream."""
    rng = random.Random(f"battle persona refills {world_seed}")
    while True:
        k = rng.choice(COHORTS)
        yield k, rng.randrange(len(PERSONAS[k]))
