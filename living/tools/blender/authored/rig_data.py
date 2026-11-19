"""Keep Blender-authored secondary animation attached by bone name across re-exports."""
from copy import deepcopy


def rebind(secondary, lookup):
    data=deepcopy(secondary)
    for g in data["boneGroups"]:
        g["bones"]=[lookup[b] for b in g["bones"]]
        if g["center"] != -1:
            g["center"]=lookup[g["center"]]
    for g in data["colliderGroups"]:
        g["node"]=lookup[g["node"]]
    return data
