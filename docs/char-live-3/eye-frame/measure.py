"""Measure native landmarks, ordered screen-left then screen-right in each shot."""
import argparse
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent


def measure(view, root):
    with Image.open(root / view["source"]) as frame:
        width, height = frame.size
    h = view["chin"] - view["hairline"]
    left, right = [eye["pupil"] for eye in view["eyes"]]
    slope = (right[1] - left[1]) / (right[0] - left[0])
    result = []
    for eye in view["eyes"]:
        x, y = eye["pupil"]
        inner, outer = eye["inner_outer_x"]
        iris_left, iris_right = eye["iris_x"]
        upper, lower = eye["aperture_y"]
        sx, sy = eye["outer_station"]
        assert sx == round(inner + (outer-inner)*5/6)
        assert 0 <= min(inner,outer) < iris_left < x < iris_right < max(inner,outer) < width
        assert 0 <= view["hairline"] < upper < y < lower < view["chin"] < height
        result.append({
            "opening_over_face_height": round((lower-upper)/h, 4),
            "outer_lid_above_pupil_axis_over_face_height": round((y+slope*(sx-x)-sy)/h, 4),
            "iris_width_over_eye_width": round((iris_right-iris_left)/abs(outer-inner), 4),
        })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("landmarks", nargs="?", type=Path, default=HERE/"landmarks.json")
    args = parser.parse_args()
    views = json.loads(args.landmarks.read_text())
    print(json.dumps({k: measure(v, args.landmarks.parent) for k,v in views.items()}, indent=2))
