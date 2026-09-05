"""Reviewable initial habits, installed as ordinary revisable participant policies.

These profiles are scenario content. Neither names nor roles select engine behavior.
Changing an existing profile's semantics requires a revision bump.
"""


def action(skill, **kwargs):
    return {"kind": "action", "action": {"skill": skill, **kwargs}}


def resource(name, comparison, value):
    return {"kind": "resource", "resource": name, "comparison": comparison, "value": value}


def negate(condition):
    return {"kind": "not", "condition": condition}


def guarded(conditions, child):
    condition = conditions[0] if len(conditions) == 1 else {"kind": "all", "conditions": conditions}
    return {"kind": "guard", "condition": condition, "child": child}


def make_starters(home):
    """Return versioned profile definitions resolved for one known home location."""
    at_home = {"kind": "at", "location": home}
    food_available = {"kind": "food_at", "location": home, "minimum": 1}

    def profile(identifier, description, reserve, rest_below, contribution=None):
        children = [
            guarded([
                resource("hunger", "at_least", 60),
                resource("food", "at_least", 1),
            ], action("eat")),
            guarded([resource("energy", "below", rest_below)], action("rest", duration=2)),
            guarded([negate(at_home)], action("move", destination=home)),
            guarded([
                at_home,
                resource("food", "below", reserve),
                food_available,
            ], action("gather")),
        ]
        if contribution is not None:
            children.append(contribution)
        # Periodically refresh direct knowledge while giving needs and others time
        # to change. The priority parent can interrupt this pause for self-care.
        children.append({"kind": "sequence", "children": [
            action("observe"), action("wait", duration=2),
        ]})
        return {
            "id": identifier,
            "revision": 1,
            "description": description,
            "tree": {"kind": "priority", "children": children},
        }

    return {
        "builder": profile(
            "settlement.builder",
            "Keep two carried meals and recover energy; return home and contribute to its "
            "shared shelter until it reaches 12. Observe and wait when supplied and sheltered. "
            "This is a starting habit that can be revised through experience.",
            reserve=2,
            rest_below=24,
            contribution=guarded([
                at_home,
                negate({"kind": "shelter_at", "location": home, "minimum": 12}),
                resource("energy", "at_least", 8),
            ], action("build")),
        ),
        "reserve_keeper": profile(
            "settlement.reserve-keeper",
            "Keep up to four carried meals from observed local supplies, recover energy, "
            "and return home when away. Observe and wait once the reserve is met; no default "
            "sharing obligation. This starting habit can be revised through experience.",
            reserve=4,
            rest_below=35,
        ),
        "shared_provider": profile(
            "settlement.shared-provider",
            "Keep two carried meals and recover energy at home. Deposit carried surplus "
            "only with at least four meals and observed public stock below four; gathering "
            "stops at two, so it cannot replenish that surplus for a gather/deposit cycle. "
            "Observe and wait when no contribution is needed. This habit is revisable.",
            reserve=2,
            rest_below=35,
            contribution=guarded([
                at_home,
                resource("food", "at_least", 4),
                negate({"kind": "food_at", "location": home, "minimum": 4}),
            ], action("deposit")),
        ),
        "cautious_observer": profile(
            "settlement.cautious-observer",
            "Keep one carried meal, recover energy early, and return home when away. "
            "Observe nearby changes and wait rather than undertake an unverified foraging "
            "journey or assume cooperation. This starting habit can be revised through experience.",
            reserve=1,
            rest_below=50,
        ),
    }
