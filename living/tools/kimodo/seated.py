"""Fit a ground seat to the target skin and share its planted base across a clip family."""

from mathutils import Vector


def contact_vertices(sk, meshes, hips, legs):
    """Keep the skin weights of the sole and seat vertices (in the glTF rest frame)."""
    regions = {hips: "seat"}
    for side, (thigh, shin, foot, toe) in legs.items():
        regions.update({thigh: "seat", foot: side, toe: side})
    points = {"seat": [], "L": [], "R": []}
    for mesh in meshes:
        groups = {g.index: g.name for g in mesh.vertex_groups}
        for v in mesh.data.vertices:
            weights = [(groups[g.group], g.weight) for g in v.groups
                       if groups[g.group] in sk.rest and g.weight > 0]
            # A simulated hem can share a thigh or hip with the body even when
            # that body joint has the largest weight. It cannot support the pelvis.
            if not weights or any(b.startswith("J_Sec_") for b, _ in weights):
                continue
            region = regions.get(max(weights, key=lambda pair: pair[1])[0])
            if region:
                x, y, z = mesh.matrix_world @ v.co
                p = Vector((x, z, -y))
                total = sum(w for _, w in weights)
                points[region].append([(b, w / total, p - sk.rest[b]) for b, w in weights])
    return points


def ground_pose(sk, pose, points, legs, hips, fk_pose, solve_leg, plant=None, seat_weight=1.0):
    q, off = pose
    q, off = dict(q), off.copy()
    names = {b for region in points.values() for vertex in region for b, _, _ in vertex}
    names.update(b for leg in legs.values() for b in leg)

    def floor(region):
        return min(sum(w * (pos[b].y + (rot[b] @ delta).y) for b, w, delta in vertex)
                   for vertex in points[region])

    tolerance = 0.0002 * sk.unit
    rot, pos = fk_pose(sk, q, off, names)
    # During a transition a released foot keeps its clearance. A planted foot
    # meets the plane. Set the target once so a fractional plant fades linearly.
    # A moving thigh can become the lowest seat-weighted vertex during a step.
    # Only use it to constrain the pelvis while the source actually bears weight.
    targets = {side: sk.floor for side in legs}
    if plant is not None:
        for side in legs:
            targets[side] += max(0, floor(side) - sk.floor) * (1 - plant[side])

    # Moving the pelvis changes both feet; bending a thigh moves some seat vertices.
    for _ in range(8):
        clearance = floor("seat") - sk.floor
        seat = min(0, clearance) + max(0, clearance) * seat_weight
        seat_weight = 1.0 if plant is None else 0.0
        feet = {side: floor(side) - targets[side] for side in legs}
        if max(abs(v) for v in [seat, *feet.values()]) < tolerance:
            break
        lift = Vector((0, -seat, 0))
        off += lift
        for side, (thigh, shin, foot, toe) in legs.items():
            if abs(feet[side] - seat) < tolerance:
                continue
            target = pos[foot] - Vector((0, feet[side], 0))
            hip = pos[thigh] + lift
            pole = pos[shin] - pos[thigh]
            ik = solve_leg(sk, side, hip, rot[hips], target, rot[foot], rot[toe], {}, pole=pole)
            # IK supplies the new segment directions. Swing the original bones
            # into those directions so the crossed legs keep their axial twist.
            def swing(b, child, solved):
                segment = sk.rest[child] - sk.rest[b]
                return (rot[b] @ segment).rotation_difference(solved @ segment) @ rot[b]

            solved_thigh = rot[hips] @ ik[thigh]
            thigh_rot = swing(thigh, shin, solved_thigh)
            shin_rot = swing(shin, foot, solved_thigh @ ik[shin])
            q[thigh] = rot[hips].inverted() @ thigh_rot
            q[shin] = thigh_rot.inverted() @ shin_rot
            q[foot] = shin_rot.inverted() @ rot[foot]
        rot, pos = fk_pose(sk, q, off, names)
    return q, off


def apply(frames, anchor, weights, hips, spine, legs):
    """Keep the source's torso performance over a stationary cross-legged base."""
    fixed, origin = anchor
    out = []
    for (source, off), weight in zip(frames, weights):
        q = dict(source)
        for b in [hips, *(b for leg in legs.values() for b in leg)]:
            q[b] = source[b].slerp(fixed[b], weight)
        q[spine] = q[hips].inverted() @ source[hips] @ source[spine]
        out.append((q, off.lerp(origin, weight)))
    return out


def sole_refs(sk, anchor, points, legs, fk_pose):
    """The rolled boot's contact point, expressed in its foot bone's rest frame."""
    names = {b for side in legs for vertex in points[side] for b, _, _ in vertex}
    rot, pos = fk_pose(sk, *anchor, names)
    refs = {}
    for side, (_, _, foot, _) in legs.items():
        vertices = (sum((w * (pos[b] + rot[b] @ delta) for b, w, delta in vertex), Vector())
                    for vertex in points[side])
        low = min(vertices, key=lambda p: p.y)
        refs[side] = sk.rest[foot] + rot[foot].inverted() @ (low - pos[foot])
    return refs
