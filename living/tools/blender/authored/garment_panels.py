"""Fit turned lapels, pocket welts and the placket to the open coat."""
from math import pi, sin

from .atelier import strip, surface


def front_top(ob, x):
    # The top front cloth at this column includes the physical collar. Project
    # onto the front half only, so an open V cannot attach to the back yoke.
    for step in range(100):
        z = 1.56 - step * .002
        hit, point, _, _ = ob.ray_cast((x, .5, z), (0, -1, 0))
        if hit and point.y > .015:
            return z
    raise ValueError(f"No front neckline on {ob.name} at x={x:.3f}")


def fitted(ob, arm, raw, dye):
    """The neckline sets each lapel root. The lower ends stop above the hips."""
    parts = []
    for side in (-1, 1):
        rows = []
        across = (-1, -.80, 0, .80, 1)
        roots = [front_top(ob, side*(.074 + q*.006)) for q in across]
        for i in range(23):
            t = i / 22
            # The lapel turns outward before tapering into the open front.
            centre = .074 * (1-t) + .055 * t + .022*sin(pi*t)
            width = .006 + .020*sin(pi*t)**.7
            row = []
            for q, root in zip(across, roots):
                x = side * (centre + q*width)
                z = (root-.008)*(1-t) + 1.28*t
                row.append(surface(ob, x, z, .0035 + .007*(1-abs(q))))
            rows.append(row)
        tones = [.24, .44, .57, .75, .41]
        parts.append(strip(ob, arm, raw, rows, [tuple(c*v for v in dye) for c in tones], (.51,.02,.98,.98)))
        # Two patch pockets with a raised welt, in the same cloth draw.
        pocket = []
        for height, ease in ((.93,.003), (.94,.005), (1.03,.006), (1.036,.010), (1.043,.009)):
            pocket.append([surface(ob, side*(.104 + q*.030), height + .004*q, ease)
                           for q in (-1, -.85, .85, 1)])
        parts.append(strip(ob, arm, raw, pocket, [tuple(c*v for v in dye)
                           for c in (.70,.96,.96,.70)], (.02,.02,.48,.98)))
    # Follow the button side down the open coat.
    centre = .063
    rows = []
    for i in range(17):
        t = i / 16
        rows.append([surface(ob, centre + .009*q, 1.28-.17*t, .004+.003*(1-abs(q)))
                     for q in (-1,-.8,0,.8,1)])
    parts.append(strip(ob, arm, raw, rows, [tuple(c*v for v in dye) for c in (.28,.46,.52,.60,.35)],
                       (.02,.02,.48,.98)))
    return parts
