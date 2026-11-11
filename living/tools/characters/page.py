#!/usr/bin/env python3
"""Write the character check page from media.py's output: ours beside the VRoid control.

    python3 living/tools/characters/page.py PAGE_DIR [--notes notes.json]

PAGE_DIR holds img/, clips/, stats.json and (optionally) town.json (media.py). Writes
PAGE_DIR/index.html, which refers to them by relative paths, so the folder can be moved or packed
as it is. Sections appear for the media that exists.

`--notes` is a JSON file of HTML fragments written for one report: `title`, `sub`, `verdict`,
`weak`, `holds`, `log`, `next`, `licences`, `captions` (picture name -> caption, replacing the
default), and `motions` (`title`, `html`, `clips`, `captions` by clip: more clips under section 2). The pictures and tables are the tool's; the judgement is the report's.
"""

import argparse
import html
import json
import os

CSS = """
:root { --bg:#f6f5f1; --fg:#1f2328; --mute:#5d6570; --card:#ffffff; --line:#d9d6cc; --accent:#8a5a12; --bad:#8f2d22; --good:#2f6b4f; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181b; --fg:#e6e3da; --mute:#a0a6ad; --card:#1f2226; --line:#34383e; --accent:#e0b060; --bad:#e58a7c; --good:#7fc7a2; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1280px; margin:0 auto; padding:24px 16px 80px; }
h1 { font-size:30px; line-height:1.2; margin:8px 0 4px; }
h2 { font-size:22px; margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); }
h3 { font-size:17px; margin:22px 0 6px; }
p, li { max-width:80ch; }
.sub { color:var(--mute); margin:0 0 18px; }
.verdict { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--accent); padding:14px 18px; border-radius:6px; margin:18px 0; }
.verdict p { margin:6px 0; }
.grid { display:grid; gap:10px; margin:10px 0 6px; }
.g2 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns:repeat(3, minmax(0, 1fr)); }
.g4 { grid-template-columns:repeat(4, minmax(0, 1fr)); } .g6 { grid-template-columns:repeat(6, minmax(0, 1fr)); }
@media (max-width:760px) { .g3, .g4, .g6 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .g2 { grid-template-columns:1fr; } }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:6px; overflow:hidden; }
figure img, figure video { display:block; width:100%; height:auto; }
figcaption { padding:6px 10px 8px; font-size:13.5px; color:var(--mute); }
figcaption b { color:var(--fg); }
.wide { overflow-x:auto; } .wide img { width:auto; max-width:none; height:auto; }
table { border-collapse:collapse; margin:10px 0; font-size:14.5px; display:block; overflow-x:auto; max-width:100%; }
th, td { border:1px solid var(--line); padding:5px 10px; text-align:left; vertical-align:top; }
th { background:var(--card); } td.n { text-align:right; font-variant-numeric:tabular-nums; }
code { font:13.5px ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--card); border:1px solid var(--line); border-radius:4px; padding:0 4px; }
.weak li b { color:var(--bad); } .ok li b { color:var(--good); }
.labels { display:grid; font-size:13.5px; color:var(--mute); padding:6px 10px 0; } .labels b { color:var(--fg); }
.axis { display:grid; font-size:12.5px; color:var(--mute); padding:5px 0 0; text-align:center; }
"""

WHO = {"ours": "<b>Ours</b>: the man", "woman": "<b>Ours</b>: the woman", "vroid": "<b>VRoid</b>: Sendagaya Shino, unchanged"}
CLIPS = [
    ("idle-tq", "<b>idle</b>, 4 s at 12 fps"), ("sword_slash-tq", "<b>sword_slash</b> (one strike), 15 fps; no weapon prop"), ("walk-tq", "<b>walk</b>, the loop four times"),
    ("walk-side", "<b>walk</b> from the side"), ("run-tq", "<b>run</b>, the loop six times"), ("run-side", "<b>run</b> from the side"), ("sit_down-tq", "<b>sit_down</b>"),
    ("sit_idle-tq", "<b>sit_idle</b>, 2 s. The takes recline as if against a backrest (a known flaw of the library)"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page")
    ap.add_argument("--notes")
    a = ap.parse_args()
    notes = json.load(open(a.notes)) if a.notes else {}
    caps = notes.get("captions", {})
    st = json.load(open(os.path.join(a.page, "stats.json")))
    have = lambda f: os.path.exists(os.path.join(a.page, f))
    kib = lambda b: f"{b / 1024:,.0f} KiB"

    def fig(src, cap, cls=""):
        cap = caps.get(os.path.basename(src), cap)
        return f'<figure class="{cls}"><a href="{src}"><img loading="lazy" src="{src}" alt="{html.escape(cap, quote=True)}"></a><figcaption>{cap}</figcaption></figure>' if have(src) else ""

    who = [w for w in ("ours", "woman", "vroid") if have(f"img/{w}-front.jpg")]

    def row(shot, ext="jpg"):
        return f'<div class="grid g{len(who)}">' + "".join(fig(f"img/{w}-{shot}.{ext}", WHO[w]) for w in who) + "</div>"

    # Who is in each clip, left to right (media.py; an older page's list named them for all).
    taken = json.load(open(os.path.join(a.page, "clips.json"))) if have("clips.json") else {}
    everyone = taken if isinstance(taken, list) else [w for w in ("ours", "woman", "vroid") if have(f"img/{w}-front.jpg")]
    taken = taken if isinstance(taken, dict) else {}

    def video(name, cap):
        if not have(f"clips/{name}.mp4"):
            return ""
        side = taken.get(name, everyone)
        labels = "".join(f"<span>{WHO[w]}</span>" for w in side)
        return (f'<figure><div class="labels" style="grid-template-columns:repeat({len(side)}, 1fr)">{labels}</div>'
                f'<video src="clips/{name}.mp4" controls loop muted autoplay playsinline></video><figcaption>{cap}</figcaption></figure>')

    def sheet(name, cap, axis=None, below=None):
        """A sheet with labels over its columns (`axis`) and, for a second row, under them (`below`)."""
        if not have(f"img/{name}"):
            return ""
        ax = lambda xs: f'<div class="axis" style="grid-template-columns:repeat({len(xs)}, 1fr)">{"".join(f"<span>{x}</span>" for x in xs)}</div>' if xs else ""
        return f'<figure>{ax(axis)}<a href="img/{name}"><img loading="lazy" src="img/{name}" alt="{html.escape(cap, quote=True)}"></a>{ax(below)}<figcaption>{caps.get(name, cap)}</figcaption></figure>'

    def parts_row(s):
        return ", ".join(f"{k} {n:,}" for k, n in sorted(s["parts"].items(), key=lambda x: -x[1]))

    out = []
    out.append(f"<h1>{notes.get('title', 'Character check: ours beside the VRoid control')}</h1>")
    out.append(f'<p class="sub">{notes.get("sub", "Every picture and clip is the game\'s own renderer (<code>living/tools/view_assets.sh</code>).")}</p>')
    if notes.get("verdict"):
        out.append(f'<div class="verdict">{notes["verdict"]}</div>')
    # 1. Stills.
    out.append("<h2>1. Stills, side by side</h2>")
    out.append("<p>The same shots for each column, through the game's renderer. The pose is the library's <code>idle</code> at 1.0 s. The view frames each figure by its own size; the close face shots of ours are scaled so the heads match the control's in the frame (its head is larger for its body).</p>")
    for title, shot in (("Front", "front"), ("Three-quarter", "three-quarter"), ("Close face", "face"), ("Three-quarter face", "face-three-quarter"), ("Side face", "face-side")):
        out.append(f"<h3>{title}</h3>{row(shot)}")
    out.append(f"<h3>The game camera (22 m, 28° down), whole frame at 1600×900</h3>{row('game')}")
    out.append("<p>At this distance a character is about 35 pixels tall. The same frames, the middle 200×150 pixels enlarged four times without smoothing:</p>" + row("game-crop", "png"))
    # 2. Clips.
    if any(have(f"clips/{n}.mp4") for n, _ in CLIPS):
        out.append("<h2>2. Clips, the same frames for each</h2>")
        out.append("<p>Every character plays the same cached Kimodo takes, retargeted by <code>animate.py</code> with no change to it. Frames are poses held at fixed times, so VRoid's spring bones (hair, skirt) rest here; in play they swing, and ours has none.</p>")
        out.append('<div class="grid g2">' + "".join(video(n, c) for n, c in CLIPS) + "</div>")
    # Other motions photographed whole (capture.sh `motions`), with the report's verdicts.
    if notes.get("motions"):
        m = notes["motions"]
        out.append(f"<h3>{m.get('title', 'More motions')}</h3>{m.get('html', '')}")
        vids = "".join(video(f"{c}-{v}", f"<b>{c}</b>{', from the side' if v == 'side' else ''}{'. ' + m.get('captions', {}).get(c, '') if m.get('captions', {}).get(c) else ''}") for c in m.get("clips", []) for v in ("tq", "side"))
        out.append(f'<div class="grid g2">{vids}</div>')
    # 3. The town.
    if have("img/town-faces-24.jpg"):
        town = json.load(open(os.path.join(a.page, "town.json"))) if have("town.json") else {"people": []}
        people = town["people"]
        kinds = {}
        for p in people:
            q = p["params"]
            k = ("child" if q["age"] < 16 else "elder" if q["age"] >= 60 else "adult")
            kinds[k] = kinds.get(k, 0) + 1
        out.append("<h2>3. Sixty-four people</h2>")
        out.append(f"<p>{len(people)} people from one command (<code>living/tools/characters/town.py</code>): {kinds.get('adult', 0)} adults, {kinds.get('elder', 0)} elders and {kinds.get('child', 0)} children in "
                   f"{len({p.get('household') for p in people})} households, drawn as a stand-in for Cullet's cast (the residents' sheets do not exist yet). Each is its own file and its own photograph. A household stands together; blood relatives share a family seed.</p>")
        out.append("<h3>24 faces, close</h3>" + sheet("town-faces-24.jpg", "24 of the 64, spread through the town, each from its own close photograph."))
        out.append("<h3>Every face</h3>" + sheet("town-faces.jpg", "All 64 in the town's order, 16 to a row. Open for full size."))
        out.append("<h3>The line-up</h3>" + sheet("town-lineup.jpg", "All 64 at one scale, from the front at the game camera's angle (28° down)."))
        out.append("<h3>Through the game camera itself</h3>" + sheet("town-game.png", "Each person at 22 m through the game camera, the frame's pixels enlarged three times without smoothing: what a player sees of them."))
    # 4. Parameters.
    if have("img/ages-m.jpg") or have("img/sweep-shape.jpg"):
        out.append("<h2>4. The parameters at work</h2>")
        out.append("<p>Each sheet changes one thing and holds the rest (<code>living/tools/characters/faces.py</code>; rest pose, no clips). <code>docs/CHARACTERS.md</code> has the reference.</p>")
        ages = ["2", "6", "10", "15", "22", "35", "50", "65", "78"]
        out.append("<h3>One seed from 2 to 78</h3>" + sheet("ages-m.jpg", "Seed 40 as a male at nine ages: only <code>age</code> changes.", ages) + sheet("ages-f.jpg", "Seed 41 as a female at the same ages.", ages))
        out.append("<h3>Face parameters, one at a time</h3><p>The same average man (every face value 0), with one value at −1, 0 and +1.</p>")
        t = lambda *names: [f"<code>{n}</code> −1 · 0 · +1" for n in names]
        out.append(sheet("sweep-shape.jpg", "The head's shape.", t("face_length", "face_width", "jaw_width", "jaw_square"), t("chin_width", "chin_length", "cheeks", "cheekbones")))
        out.append(sheet("sweep-eyes.jpg", "Eyes and brows.", t("eye_size", "eye_spacing", "eye_height", "eye_open"), t("eye_tilt", "eye_shape", "brow_thickness", "brow_tilt")))
        out.append(sheet("sweep-rest.jpg", "Brows, nose, mouth, ears.", t("brow_arch", "brow_height", "nose_width", "mouth_width"), t("lip_fullness", "mouth_curve", "ear_size", "ear_out")))
        out.append(sheet("sweep-profile.jpg", "From the side: what only the profile shows.", t("nose_length", "nose_bridge", "nose_tip"), t("chin_forward", "forehead", "brow_ridge")))
        out.append("<h3>Beards and stubble</h3>" + sheet("beards.jpg", "One man: clean, stubble, moustache, goatee, chinstrap, short, full, and the full beard at 66.", ["none", "stubble", "moustache", "goatee", "chinstrap", "short", "full", "full, age 66"]))
        out.append("<h3>Skin</h3>" + sheet("skin.jpg", "One woman at six skin tones, with freckles, and a weathered man of 45.", ["tone 0", "0.2", "0.4", "0.6", "0.8", "1.0", "freckles 1", "weathered 1"]))
        out.append("<h3>Build</h3>" + sheet("build.jpg", "Weight and muscle, in the rest pose, from the front and the side. The clothes follow the body's girth; height and a child's proportions are the recipe's.", ["weight −1", "0", "+1", "muscle +1", "weight −1", "0", "+1", "the heavy preset"]))
        out.append("<h3>Expressions</h3>" + sheet("expressions.jpg", "Morph targets under VRoid's names, set in the file to photograph them: neutral; both eyes closed; <code>Fcl_EYE_Joy</code> with a smile; <code>Fcl_MTH_O</code> with raised brows; <code>Fcl_MTH_E</code>; angry brows; sorrow; a wink.",
                                                 ["neutral", "eyes closed", "joy", "O, surprised", "E", "angry", "sorrow", "wink"]))
        blink = "".join(fig(f"img/{w}-{k}.jpg", f"{WHO[w]}: {c}") for w in ("ours", "woman") for k, c in (("blink-open", "open"), ("blink-shut", "a blink"), ("mouth-open", "the mouth open while talking")))
        if blink:
            out.append("<p>The game drives <code>Fcl_EYE_Close</code> and <code>Fcl_MTH_A</code> itself. These frames are from the game with its own blink and talking mouth running:</p>" + f'<div class="grid g6">{blink}</div>')
    # 5. Looked at hard.
    out.append("<h2>5. Looked at hard</h2>")
    if have("img/eye-close.jpg"):
        out.append("<h3>Eyes, very close</h3>" + sheet("eye-close.jpg", "The woman, the man, the girl, the elder, 25° to the side. The lids pass in front of the eye; the white, iris and highlights are paint on a bowl behind them; the lash line, lower line and fold are shapes just off the skin."))
    atlas = "".join(fig(f"img/{w}-atlas.png", f"The {n}'s atlas, 1024×1024: the eyes' strip, the swatch for the ears, the whole head's skin unrolled with the face widest.") for w, n in (("woman", "woman"), ("ours", "man")))
    if atlas:
        out.append("<h3>The painted face</h3><p>One texture a person, painted by <code>face_paint.py</code> from the head's form: nothing is drawn by hand or taken from a file.</p>" + f'<div class="grid g2">{atlas}</div>')
    pairs = lambda shots: "".join(fig(f"img/{w}-{s}.jpg", f"{WHO[w]}{', ' + c if c else ''}") for s, c in shots for w in ("ours", "vroid"))
    out.append("<h3>Hands, joints, sitting</h3><p>The body, hands and clothes are the spike's, unchanged in this pass.</p>")
    out.append(f'<div class="grid g4">{pairs((("hands", "<code>talk</code> at 2.0 s"), ("shoulder", "<code>wave</code> at 1.4 s"), ("elbow", "<code>sword_slash</code> at 1.25 s"), ("knee", "<code>run</code> at 0.2 s"), ("hip", "<code>sit_idle</code>"), ("sit-three-quarter", "")))}</div>')
    others = "".join(fig(f"img/{k}-face.jpg", c) + fig(f"img/{k}-front.jpg", c) for k, c in (("elder", "The elder preset (70)"), ("heavy", "The heavy preset (44)"), ("youth", "The youth preset (15)"), ("boy", "The boy preset (8)"), ("girl", "The girl preset (6)")))
    if others:
        out.append("<h3>The other presets</h3>" + f'<div class="grid g4">{others}</div>')
    # 6. Level of detail.
    if "ours" in st and "vroid" in st:
        o, v = st["ours"], st["vroid"]
        w = st.get("woman")
        out.append("<h2>6. What the files hold</h2><table>")
        out.append(f"<tr><th></th><th>Ours (the man)</th>{'<th>Ours (the woman)</th>' if w else ''}<th>VRoid (Sendagaya Shino)</th></tr>")
        cell = lambda f, cls="n": "".join(f'<td class="{cls}">{f(s)}</td>' for s in ([o, w, v] if w else [o, v]))
        out.append(f"<tr><td>Triangles</td>{cell(lambda s: format(s['triangles'], ','))}</tr>")
        out.append(f"<tr><td>Vertices in the file</td>{cell(lambda s: format(s['vertices'], ','))}</tr>")
        out.append(f"<tr><td>Triangles by part</td>{cell(parts_row, '')}</tr>")
        out.append(f"<tr><td>Bones</td>{cell(lambda s: str(s['bip_bones']) + ' J_Bip, ' + str(s['spring_bones']) + ' spring')}</tr>")
        out.append(f"<tr><td>Materials</td>{cell(lambda s: len(s['materials']))}</tr>")
        out.append(f"<tr><td>Textures</td>{cell(lambda s: str(s['textures']) + ', ' + kib(s['texture_bytes']))}</tr>")
        out.append(f"<tr><td>Morph targets</td>{cell(lambda s: s['morph_targets'])}</tr>")
        out.append(f"<tr><td>File</td>{cell(lambda s: kib(s['bytes']) + ' with ' + str(len(s['clips'])) + ' clips')}</tr>")
        out.append("</table>")
    for key, title, cls in (("weak", "7. What is weak", "weak"), ("holds", "What holds up", "ok")):
        if notes.get(key):
            out.append((f"<h2>{title}</h2>" if key == "weak" else f"<h3>{title}</h3>") + f'<div class="{cls}">{notes[key]}</div>')
    if notes.get("log"):
        out.append(f"<h2>8. Time and attempts</h2>{notes['log']}")
    if notes.get("next"):
        out.append(f"<h2>9. What pass 2 should do</h2>{notes['next']}")
    if notes.get("licences"):
        out.append(f"<h2>10. Licences and how to make this page again</h2>{notes['licences']}")
    body = "\n".join(x for x in out if x)
    title = html.escape(notes.get("page_title", "Character check"))
    doc = f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n<style>{CSS}</style></head>\n<body><main>{body}</main></body></html>\n'
    with open(os.path.join(a.page, "index.html"), "w") as f:
        f.write(doc)
    print(f"wrote {os.path.join(a.page, 'index.html')} ({len(doc) // 1024} KiB)")


if __name__ == "__main__":
    main()
