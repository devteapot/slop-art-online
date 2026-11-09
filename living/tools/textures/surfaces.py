"""The painted surfaces of models: the detail layers the toon shader multiplies into scenery's
vertex colours (living/game/src/style.rs `Surface`, in this order).

paint.py paints them (`--set material`, layer k of `material.png`). The Blender generators
(living/tools/blender/nature.py, buildings.py) tag each part with its surface in the alpha of
its vertex colour, so the game picks a layer per vertex while every model keeps sharing one
material. Untagged parts (alpha 1) get no detail.
"""

SURFACES = ["bark", "leaves", "wood", "planks", "plaster", "stone", "boulder", "brick", "shingles", "tiles", "thatch", "metal", "copper", "concrete", "cloth", "glass"]

# Alpha codes: surface k is (k + 0.5) / 32; the shader takes floor(alpha * 32) and treats 16
# and up (alpha 1) as untagged. Byte colours keep about 1/255, well inside each step.
STEPS = 32


def alpha(surface: str | None) -> float:
    """The vertex-colour alpha that tags a part with `surface` (None: untagged)."""
    if surface is None:
        return 1.0
    return (SURFACES.index(surface) + 0.5) / STEPS
