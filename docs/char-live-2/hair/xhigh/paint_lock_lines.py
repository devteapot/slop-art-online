"""Draw Cora's one-texel lock boundaries in her UV0 layout, before ink_field.py."""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw


# Start and end of the visible boundary, and its widthwise position at the
# root, bend and tip. Each entry follows the corresponding modelled sweep.
SWEEPS = {
    0: (.07, .94, .59, .77, .43), 1: (.10, .92, .51, .55, .41),
    2: (.05, .96, .50, .55, .42), 3: (.11, .96, .43, .36, .42),
    4: (.39, .91, .39, .65, .47), 5: (.12, .92, .37, .32, .44),
    6: (.25, .92, .63, .66, .58), 7: (.06, .84, .43, .36, .55),
    8: (.12, .83, .56, .45, .49), 9: (.08, .98, .61, .64, .58),
    10: (.19, .93, .38, .34, .45), 11: (.11, .96, .63, .68, .56),
    12: (.17, .94, .38, .36, .46), 16: (.20, .83, .40, .34, .45),
}


def paint(layout, output):
    spec = json.loads(Path(layout).read_text())
    size = spec["size"]
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    braid = 0
    for tile in spec["islands"]:
        left, top, right, bottom = tile["box"]
        kind, seed = tile["kind"], tile["seed"]

        def stroke(points):
            span = tile.get("angular_span", 1.0)
            for turn in range(math.ceil(span)):
                visible = [(round(left + (right - left) * (x + turn) / span),
                            round(top + (bottom - top) * y))
                           for x, y in points if x + turn <= span]
                if len(visible) >= 2:
                    draw.line(visible, fill=0, width=1)

        def boundary(start, end, root, bend, tip):
            # A single antialiased stroke comes from the client's field sampler.
            points = []
            for index in range(121):
                t = index / 120
                x = (1 - t) ** 2 * root + 2 * t * (1 - t) * bend + t ** 2 * tip
                points.append((x, start + t * (end - start)))
            stroke(points)

        if kind == "sweep":
            boundary(*SWEEPS[seed])
        elif kind == "combed":
            side = 1 if seed > 0 else -1
            group = abs(seed)
            # Carry the side sheets to the central crossing, leaving the
            # opposite edge for the next overlapping sheet. The crown part
            # opens near the roots, then closes as the braid gathers.
            start = [.16, .10, .08, .04, .06, .04][group - 1]
            boundary(start, .97, .5 - .13 * side, .5 - .03 * side, .5 + .085 * side)
        elif kind == "braid":
            # Opposing edges of each helix follow its physical over-under
            # path. Leave short breaks at the turns where a strand dives.
            for edge in (.405, .602):
                points = []
                for row in range(401):
                    t = row / 400
                    phase = math.tau * (2.8 * t + braid / 3)
                    if math.cos(phase + (.8 if edge < .5 else -.8)) < -.88:
                        if len(points) > 1:
                            stroke(points)
                        points = []
                        continue
                    points.append((edge + .035 * math.sin(phase), t))
                if len(points) > 1:
                    stroke(points)
            # Each strand turns over twice per revolution. A short curved
            # crease turns across the lower margin of the exposed lobe.
            for crossing in range(8):
                y = (.16 + crossing * .5 - braid / 3) / 2.8
                if .035 < y < .965:
                    direction = 1 if crossing % 2 else -1
                    stroke([(.34 + .32 * t / 40, y + .028 * math.sin(math.pi * t / 40)
                             + direction * .022 * (t / 40 - .5)) for t in range(41)])
            braid += 1
        elif kind == "support":
            # The exposed part of the physical shell fills narrow gaps
            # between the swept locks at the part and down the rear midline.
            boundary(.07, .50, .54, .60, .53)
            boundary(.37, .87, .06, .06, .001)
            boundary(.37, .87, .94, .94, .999)
        elif kind == "tie":
            stroke([(.01, .16), (.99, .16)])
            stroke([(.01, .79), (.99, .79)])
        elif kind == "brush":
            boundary(.05, .90, .37, .29, .49)
            boundary(.08, .74, .64, .72, .55)
    image.save(output)


if __name__ == "__main__":
    paint(*sys.argv[1:])
