"""Fit the atelier's turned lapels and folded placket to shared outfit pieces."""
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


def fitted(ob, arm, raw):
    """The neckline sets each lapel root. The lower ends stop above the hips."""
    coat = ob.name.split('.')[0] == 'Coat'
    parts = []
    for side in (-1, 1):
        rows = []
        across = (-1, -.80, 0, .80, 1)
        roots = [front_top(ob, side*(.074 + q*.006)) for q in across]
        for i in range(23):
            t = i / 22
            # Coat fronts stay separated down the chest; the vest closes at centre.
            centre = .074 * (1-t) + (.055 if coat else .012) * t + .022*sin(pi*t)
            width = .006 + .020*sin(pi*t)**.7
            row = []
            for q, root in zip(across, roots):
                x = side * (centre + q*width)
                z = (root-.008)*(1-t) + 1.28*t
                row.append(surface(ob, x, z, .0035 + .007*(1-abs(q))))
            rows.append(row)
        tones = [.50, .93, .94, .98, .53]
        parts.append(strip(ob, arm, raw, rows, [(c,)*3 for c in tones], (.51,.02,.98,.98)))
    # Follow the button side on an open coat. Place the vest placket centrally.
    centre = .063 if coat else 0
    rows = []
    for i in range(17):
        t = i / 16
        rows.append([surface(ob, centre + .009*q, 1.28-.17*t, .004+.003*(1-abs(q)))
                     for q in (-1,-.8,0,.8,1)])
    parts.append(strip(ob, arm, raw, rows, [(c,)*3 for c in (.55,.91,.80,.92,.58)],
                       (.02,.02,.48,.98)))
    return parts
