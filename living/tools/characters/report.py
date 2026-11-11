#!/usr/bin/env python3
"""A pass's report page: every close-up with the accepted version and the reference beside it.

    python3 living/tools/characters/report.py PAGE_DIR --notes notes.json [--board ~/archive/asset-board]

The pictures of the characters come from the asset board's media (docs/ASSET_BOARD.md), which
photographs every family with the same shots: for each family named in the notes this page sets
the version accepted before (`before`), this pass's version (`after`) and the control from the
same publish side by side, shot by shot. Everything else is in the notes file, a JSON object:

    title, sub, verdict (HTML)
    families: [{family, member, label, before, after, control}]   version ids; control a member name
    closeups: [shot, …]   the shots shown for every family, in rows of before / after / reference
    figures:  [shot, …]   the same, for whole-figure shots
    clips:    [name, …]   board clips shown for the first families (ours beside the control)
    sections: [{title, html, pictures: [{src, caption, wide}], columns}]   in page order; `src` is a
              path (copied into PAGE_DIR/img, made a JPEG if large) or a board path
              `board:<family>/<version>/<member>/<shot>.jpg`
    after_closeups: index in `sections` after which the close-up comparison goes (default 0)

Writes PAGE_DIR/index.html and PAGE_DIR/img, PAGE_DIR/clips: the folder can be moved or packed
as it is. Needs Pillow.
"""

import argparse
import html
import json
import os
import shutil

from PIL import Image

CSS = """
:root { --bg:#f6f5f1; --fg:#1f2328; --mute:#5d6570; --card:#ffffff; --line:#d9d6cc; --accent:#8a5a12; --ref:#2f5f8f; --old:#7a7a7a; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181b; --fg:#e6e3da; --mute:#a0a6ad; --card:#1f2226; --line:#34383e; --accent:#e0b060; --ref:#8fc0ee; --old:#9a9a9a; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1320px; margin:0 auto; padding:24px 16px 80px; }
h1 { font-size:30px; line-height:1.2; margin:8px 0 4px; }
h2 { font-size:22px; margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); }
h3 { font-size:17px; margin:22px 0 6px; }
p, li { max-width:84ch; }
.sub { color:var(--mute); margin:0 0 18px; }
.verdict { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--accent); padding:14px 18px; border-radius:6px; margin:18px 0; }
.verdict p { margin:6px 0; }
.grid { display:grid; gap:10px; margin:10px 0 6px; }
.g1 { grid-template-columns:1fr; } .g2 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns:repeat(3, minmax(0, 1fr)); }
.g4 { grid-template-columns:repeat(4, minmax(0, 1fr)); } .g6 { grid-template-columns:repeat(6, minmax(0, 1fr)); }
@media (max-width:760px) { .g4, .g6 { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:6px; overflow:hidden; }
figure img, figure video { display:block; width:100%; height:auto; }
figcaption { padding:6px 10px 8px; font-size:13.5px; color:var(--mute); }
figcaption b { color:var(--fg); }
.tag { display:inline-block; font-size:12px; font-weight:600; padding:1px 7px; border-radius:10px; border:1px solid currentColor; margin-right:6px; }
.before { color:var(--old); } .after { color:var(--accent); } .ref { color:var(--ref); }
.sheet { overflow-x:auto; border:1px solid var(--line); border-radius:6px; background:var(--card); }
.sheet img { display:block; max-width:none; }
table { border-collapse:collapse; font-size:14px; display:block; overflow-x:auto; margin:10px 0; }
th, td { border:1px solid var(--line); padding:4px 10px; text-align:left; vertical-align:top; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
code { font-size:0.92em; }
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page")
    ap.add_argument("--notes", required=True)
    ap.add_argument("--board", default=os.path.expanduser(os.environ.get("ASSET_BOARD_HOME", "~/archive/asset-board")))
    a = ap.parse_args()
    notes = json.load(open(a.notes))
    page = os.path.abspath(a.page)
    os.makedirs(os.path.join(page, "img"), exist_ok=True)
    os.makedirs(os.path.join(page, "clips"), exist_ok=True)
    base = os.path.dirname(os.path.abspath(a.notes))
    used = {}

    def take(src, max_side=1400):
        """Copy a picture into the page (a JPEG no larger than max_side) and return its path there."""
        if src.startswith("board:"):
            path = os.path.join(a.board, "media", src[6:])
            name = src[6:].replace("/", "-")
        else:
            path = src if os.path.isabs(src) else os.path.join(base, src)
            name = os.path.basename(path)
        if path in used:
            return used[path]
        if not os.path.exists(path):
            raise SystemExit(f"report: no picture {path}")
        stem, ext = os.path.splitext(name)
        k = 1
        while any(os.path.basename(v) in (stem + ".jpg", stem + ".png") for v in used.values()):
            stem = f"{os.path.splitext(name)[0]}-{k}"
            k += 1
        im = Image.open(path)
        if ext.lower() == ".png" and max(im.size) <= 1700 and "crop" in name:
            out = f"img/{stem}.png"  # enlarged pixels stay exact
            shutil.copy(path, os.path.join(page, out))
        else:
            im = im.convert("RGB")
            if max(im.size) > max_side and not notes.get("full_size", {}).get(os.path.basename(path)):
                k = max_side / max(im.size)
                im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
            out = f"img/{stem}.jpg"
            im.save(os.path.join(page, out), quality=88)
        used[path] = out
        return out

    def fig(src, caption, cls=""):
        return f'<figure><img loading="lazy" src="{take(src)}" alt="{html.escape(caption_text(caption))}"><figcaption>{caption}</figcaption></figure>'

    def caption_text(c):
        import re
        return re.sub(r"<[^>]+>", "", c)

    def rows(shots, names):
        out = []
        for f in notes["families"]:
            slug = f["family"].replace(":", "-")
            out.append(f"<h3>{html.escape(f['label'])}</h3>")
            for shot in shots:
                cells = []
                if f.get("before"):
                    cells.append(fig(f"board:{slug}/{f['before']}/{f['member']}/{shot}", f'<span class="tag before">Pass 1</span>{names.get(shot, shot)}'))
                cells.append(fig(f"board:{slug}/{f['after']}/{f['member']}/{shot}", f'<span class="tag after">Pass 2</span>{names.get(shot, shot)}'))
                cells.append(fig(f"board:{slug}/{f['after']}/{f.get('control', 'vroid')}/{shot}", f'<span class="tag ref">Reference</span>{names.get(shot, shot)}'))
                out.append(f'<div class="grid g{len(cells)}">{"".join(cells)}</div>')
        return "".join(out)

    names = notes.get("shot_names", {})
    body = [f"<h1>{notes['title']}</h1>", f'<p class="sub">{notes["sub"]}</p>', f'<div class="verdict">{notes["verdict"]}</div>']
    sections = notes["sections"]
    at = notes.get("after_closeups", 0)
    for i, sec in enumerate(sections):
        if i == at and notes.get("closeups"):
            body.append(f"<h2>{notes.get('closeups_title', 'Close up, beside the reference')}</h2>{notes.get('closeups_html', '')}")
            body.append(rows([s + ".jpg" for s in notes["closeups"]], names))
        body.append(f"<h2>{sec['title']}</h2>{sec.get('html', '')}")
        if sec.get("figures"):
            body.append(rows([s + (".png" if s.endswith("-crop") else ".jpg") for s in sec["figures"]], names))
        for clip in sec.get("clips", []):
            cells = []
            for f in notes["families"][: sec.get("clip_families", 2)]:
                slug = f["family"].replace(":", "-")
                for member, tag, cls in ((f["member"], f["label"], "after"), (f.get("control", "vroid"), "Reference", "ref")):
                    src = os.path.join(a.board, "media", slug, f["after"], member, "clips", clip + ".mp4")
                    if not os.path.exists(src):
                        continue
                    dst = f"clips/{slug}-{member}-{clip}.mp4"
                    if (f.get("control", "vroid") == member) and any(c[0] == clip + "-ref" for c in cells):
                        continue
                    shutil.copy(src, os.path.join(page, dst))
                    cells.append((clip + ("-ref" if cls == "ref" else ""), f'<figure><video src="{dst}" controls loop muted playsinline preload="metadata"></video><figcaption><span class="tag {cls}">{html.escape(tag)}</span>{html.escape(clip)}</figcaption></figure>'))
            if cells:
                body.append(f'<div class="grid g{len(cells)}">{"".join(c for _, c in cells)}</div>')
        pics = sec.get("pictures", [])
        wide = [p for p in pics if p.get("wide")]
        tiles = [p for p in pics if not p.get("wide")]
        if tiles:
            body.append(f'<div class="grid g{sec.get("columns", min(len(tiles), 4))}">{"".join(fig(p["src"], p.get("caption", "")) for p in tiles)}</div>')
        for p in wide:
            full = take(p["src"], max_side=p.get("max_side", 2400))
            body.append(f'<figure class="sheet"><a href="{full}"><img loading="lazy" src="{full}" style="width:{p.get("width", "100%")};max-width:{p.get("max_width", "100%")}" alt=""></a></figure><p class="sub">{p.get("caption", "")}</p>')
        body.append(sec.get("html_after", ""))
    doc = f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{caption_text(notes["title"])}</title><style>{CSS}</style><main>{"".join(body)}</main></html>'
    with open(os.path.join(page, "index.html"), "w") as f:
        f.write(doc)
    print(f"wrote {os.path.join(page, 'index.html')}: {len(used)} pictures, {len(os.listdir(os.path.join(page, 'clips')))} clips")


if __name__ == "__main__":
    main()
