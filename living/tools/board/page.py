"""The board's pages: index.html (every family, accepted beside latest) and family/<family>.html
(the latest version beside the accepted one, shot by shot, with diffs, a flicker, the numbers,
the palette and the clips; then every version and decision). Static HTML with relative paths and
a few lines of script, so the folder works from a tarball on any machine. The style is the
character spike page's (living/tools/char_spike/page.py, now living/tools/characters/)."""

import html
import json
import os
from urllib.parse import quote

import diff as D
import glb as G

CSS = """
:root { --bg:#f6f5f1; --fg:#1f2328; --mute:#5d6570; --card:#ffffff; --line:#d9d6cc; --accent:#8a5a12; --bad:#8f2d22; --good:#2f6b4f; --warn:#8a6a12; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181b; --fg:#e6e3da; --mute:#a0a6ad; --card:#1f2226; --line:#34383e; --accent:#e0b060; --bad:#e58a7c; --good:#7fc7a2; --warn:#e0c060; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1320px; margin:0 auto; padding:24px 16px 80px; }
a { color:var(--accent); }
h1 { font-size:28px; line-height:1.2; margin:8px 0 4px; }
h2 { font-size:21px; margin:40px 0 10px; padding-top:14px; border-top:1px solid var(--line); }
h3 { font-size:17px; margin:22px 0 6px; }
p, li { max-width:84ch; }
.sub { color:var(--mute); margin:0 0 18px; }
.box { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--accent); padding:12px 16px; border-radius:6px; margin:14px 0; }
.box p { margin:5px 0; }
.box.warn { border-left-color:var(--warn); }
.grid { display:grid; gap:10px; margin:8px 0; }
.g2 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns:repeat(3, minmax(0, 1fr)); } .g4 { grid-template-columns:repeat(4, minmax(0, 1fr)); }
.cards { display:grid; gap:14px; grid-template-columns:repeat(auto-fill, minmax(380px, 1fr)); }
@media (max-width:760px) { .g3, .g4 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .cards { grid-template-columns:1fr; } }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:6px; overflow:hidden; position:relative; }
figure img, figure video { display:block; width:100%; height:auto; }
figure .none { aspect-ratio:4/3; display:flex; align-items:center; justify-content:center; color:var(--mute); font-size:14px; }
figcaption { padding:5px 10px 7px; font-size:13.5px; color:var(--mute); }
figcaption b { color:var(--fg); }
.card { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:10px 12px; }
.card h3 { margin:2px 0 6px; } .card .grid { margin:6px 0; } .card figure { border-color:var(--line); }
.tag { display:inline-block; font-size:12.5px; padding:0 7px; border-radius:10px; border:1px solid var(--line); color:var(--mute); margin-right:4px; white-space:nowrap; }
.tag.accept { color:var(--good); border-color:var(--good); } .tag.reject { color:var(--bad); border-color:var(--bad); } .tag.pending { color:var(--warn); border-color:var(--warn); }
table { border-collapse:collapse; margin:8px 0; font-size:14px; display:block; overflow-x:auto; max-width:100%; }
th, td { border:1px solid var(--line); padding:4px 9px; text-align:left; vertical-align:top; }
th { background:var(--card); } td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.up { color:var(--warn); } td.down { color:var(--good); } td.same { color:var(--mute); }
code { font:13px ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--card); border:1px solid var(--line); border-radius:4px; padding:0 4px; }
.row { margin:14px 0 22px; } .row h4 { margin:0 0 4px; font-size:15px; }
.chg { font-variant-numeric:tabular-nums; } .chg.big { color:var(--bad); font-weight:600; } .chg.small { color:var(--mute); }
button { font:inherit; font-size:13.5px; padding:2px 10px; border-radius:5px; border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button.on { border-color:var(--accent); color:var(--accent); }
.strip { display:flex; height:22px; border-radius:4px; overflow:hidden; border:1px solid var(--line); margin:3px 0 8px; max-width:640px; }
.strip span { display:block; height:100%; }
.sw { display:inline-block; width:14px; height:14px; border-radius:3px; border:1px solid var(--line); vertical-align:-2px; margin-right:4px; }
.decide { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0; } .decide input { flex:1 1 320px; font:inherit; padding:3px 8px; border:1px solid var(--line); border-radius:5px; background:var(--bg); color:var(--fg); }
textarea.cmd { width:100%; font:13px ui-monospace, Menlo, monospace; background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:5px; padding:6px; display:none; }
details > summary { cursor:pointer; color:var(--accent); margin:6px 0; }
.thumbs { display:flex; gap:6px; overflow-x:auto; } .thumbs figure { flex:0 0 220px; }
"""

JS = r"""
function flicker(btn){const row=btn.closest('.row');const img=row.querySelector('.latest img');if(!img)return;
 const which=row.querySelector('.latest figcaption .which');
 if(btn._t){clearInterval(btn._t);btn._t=null;img.src=img.dataset.latest;if(which)which.textContent='';btn.classList.remove('on');btn.textContent='Flicker';return;}
 let a=false;btn.classList.add('on');btn.textContent='Stop';btn._t=setInterval(()=>{a=!a;img.src=a?img.dataset.base:img.dataset.latest;
 if(which)which.textContent=a?'(showing accepted)':'';},550);}
function together(btn){const vs=btn.closest('.row').querySelectorAll('video');vs.forEach(v=>{v.pause();v.currentTime=0;});vs.forEach(v=>v.play());}
function q(s){return "'"+String(s).replace(/'/g,"'\\''")+"'";}
function decide(btn,verdict){const box=btn.closest('.decidebox');const words=box.querySelector('input').value.trim();
 const cmd='python3 living/tools/board/board.py decide '+q(box.dataset.family)+' '+q(box.dataset.version)+' '+verdict+(words?' --words='+q(words):'');
 const t=box.querySelector('textarea');t.style.display='block';t.value=cmd;t.select();
 if(navigator.clipboard){navigator.clipboard.writeText(cmd).then(()=>{box.querySelector('.copied').textContent='copied: paste it to the coordinator';},()=>{});}}
"""

KEY_SHOTS = {"building": ["three-quarter", "game", "night-game", "close"], "prop": ["three-quarter", "game", "night-game", "close"],
             "character": ["front", "three-quarter", "face", "face-three-quarter", "game", "game-walk"]}
THUMB = {"building": ["three-quarter", "game", "front"], "prop": ["three-quarter", "front", "game"], "character": ["front", "three-quarter", "face"]}
HOW = {"accepted": "the accepted version", "accepted before": "the version accepted before it", "previous": "the version published before it (nothing is accepted yet)"}

e = html.escape


def u(path):
    """A relative path for an attribute: URL-encoded, then HTML-escaped."""
    return e(quote(path, safe="/#"))


def doc(title, body):
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{e(title)}</title>\n<style>{CSS}</style></head>\n<body><main>{body}</main><script>{JS}</script></body></html>\n')


def short(v):
    return v[:8] if v else ""


def img_path(home, version, member, shot):
    """(relative path from the home, exists) of a version's photograph."""
    rel = f"{version['media']}/{member}/{shot}.jpg"
    return rel, os.path.exists(os.path.join(home, rel))


def subjects(v):
    return [m for m in (v or {}).get("members", []) if m.get("role", "subject") != "control"]


def controls(v):
    return [m for m in (v or {}).get("members", []) if m.get("role") == "control"]


def member(v, name):
    return next((m for m in v.get("members", []) if m["name"] == name), None) if v else None


def fig(src, cap, cls="", extra="", up=""):
    if not src:
        return f'<figure class="{cls}"><div class="none">not photographed</div><figcaption>{cap}</figcaption></figure>'
    return f'<figure class="{cls}"><a href="{up}{u(src)}"><img loading="lazy" src="{up}{u(src)}" alt="" {extra}></a><figcaption>{cap}</figcaption></figure>'


def video(src, cap, up):
    return f'<figure><video src="{up}{u(src)}" controls loop muted playsinline preload="metadata"></video><figcaption>{cap}</figcaption></figure>'


def verdict_tag(d):
    if not d:
        return '<span class="tag pending">no decision</span>'
    return f'<span class="tag {e(d["verdict"])}">{"accepted" if d["verdict"] == "accept" else "rejected"} {e(d["date"])}{" as " + e(d["scope"]) if d.get("scope") else ""}</span>'


def source_line(v):
    s = v.get("source", {})
    bits = [f'<code>{e(s.get("branch") or "?")}@{e(short(s.get("commit")))}</code>' + (" (uncommitted changes)" if s.get("dirty") else "")]
    if s.get("generator"):
        bits.append(f'<code>{e(s["generator"])}</code>' + (f' sha256 {e(s.get("generator_sha256", "")[:10])}' if s.get("generator_sha256") else "") +
                    (f' ({e(s["generator_state"])})' if s.get("generator_state") and s.get("generator_state") != "committed" else ""))
    if s.get("seed") not in (None, ""):
        bits.append(f"seed <code>{e(str(s['seed']))}</code>")
    if s.get("params"):
        bits.append("params <code>" + e(json.dumps(s["params"], ensure_ascii=False)[:300]) + "</code>")
    return " · ".join(bits)


def renderer_line(v):
    r = v.get("renderer", {})
    if r.get("method") == "asset-view":
        hours = r.get("hours") or {}
        return (f'the game\'s asset view at <code>{e(r.get("key", ""))}</code>' + (f', environment <code>{e(r["env"])}</code>' if r.get("env") else "") +
                (", hours " + ", ".join(f"{e(k)} {h:g}" for k, h in hours.items()) if hours else "") + (f'. {e(r["note"])}' if r.get("note") else ""))
    return f'{e(r.get("method", "?"))}{" at <code>" + e(r.get("key", "")) + "</code>" if r.get("key") else ""}{". " + e(r["note"]) if r.get("note") else ""}'


# ---------------------------------------------------------------------------------------------
# Numbers


def metrics(m):
    """Flat {label: value} of what the board compares for one member."""
    if not m:
        return {}
    s = m.get("stats") or {}
    v = m.get("view") or {}
    out = {}
    for k, lab in (("triangles", "Triangles"), ("vertices", "Vertices"), ("glow_triangles", "Glowing triangles"), ("bytes", "File bytes"), ("textures", "Textures"),
                   ("texture_bytes", "Texture bytes"), ("morph_targets", "Morph targets"), ("bones", "Bones"), ("skin_joints", "Bones"), ("bip_bones", "J_Bip bones"),
                   ("spring_bones", "Spring bones")):
        if isinstance(s.get(k), (int, float)) and lab not in out:
            out[lab] = s[k]
    for k, lab in (("materials", "Materials"), ("clips", "Clips")):
        if isinstance(s.get(k), list):
            out[lab] = len(s[k])
    if isinstance(v.get("size_m"), list) and len(v["size_m"]) == 3:
        x, y, z = v["size_m"]
        out["Width (m)"], out["Height (m)"], out["Depth (m)"] = round(x, 2), round(y, 2), round(z, 2)
        out["Footprint (m²)"] = round(x * z, 1)
    for k, val in (m.get("report") or {}).items():
        if isinstance(val, (bool, int, float)):
            out[f"report: {k}"] = val
        elif isinstance(val, list) and val and len(val) <= 4 and all(isinstance(x, (int, float)) for x in val):
            out[f"report: {k}"] = " × ".join(f"{x:g}" for x in val)
        elif isinstance(val, str) and len(val) <= 40:
            out[f"report: {k}"] = val
    return out


def fmt(x):
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return f"{x:,}"
    if isinstance(x, float):
        return f"{x:,.3g}" if abs(x) < 1 else f"{x:,.2f}".rstrip("0").rstrip(".")
    return e(str(x)) if x is not None else "–"


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def metric_table(bm, lm, cms=(), base_label=None):
    a, b = metrics(bm), metrics(lm)
    cs = [(cm["name"], metrics(cm)) for cm in cms]
    keys = list(dict.fromkeys(list(b) + list(a)))
    if not keys:
        return ""
    rows = []
    for k in keys:
        x, y = a.get(k), b.get(k)
        cells = f'<td>{e(k)}</td>'
        if base_label:
            if num(x) and num(y):
                d = y - x
                pct = f" ({d / x * 100:+.0f}%)" if x else ""
                cls = "same" if d == 0 else ("up" if d > 0 else "down")
                delta = "same" if d == 0 else (f"{d:+,}" if isinstance(d, int) else f"{d:+,.2f}") + pct
            else:
                cls, delta = ("same", "same") if x == y else ("up", "changed" if x is not None and y is not None else ("new" if x is None else "gone"))
            cells += f'<td class="n">{fmt(x)}</td><td class="n">{fmt(y)}</td><td class="n {cls}">{e(delta)}</td>'
        else:
            cells += f'<td class="n">{fmt(y)}</td>'
        cells += "".join(f'<td class="n">{fmt(c.get(k))}</td>' for _, c in cs)
        rows.append(f"<tr>{cells}</tr>")
    head = "<tr><th></th>" + (f"<th>{e(base_label)}</th><th>Latest</th><th>Change</th>" if base_label else "<th>This version</th>") + "".join(f"<th>Target: {e(n)}</th>" for n, _ in cs) + "</tr>"
    return "<table>" + head + "".join(rows) + "</table>"


def strip(pal):
    if not pal:
        return '<p class="sub">No vertex colours (textured, or not measured).</p>'
    return '<div class="strip">' + "".join(f'<span title="{e(p["hex"])} {p["share"] * 100:.1f}%" style="width:{p["share"] * 100:.2f}%;background:{"#888" if p["hex"] == "other" else e(p["hex"])}"></span>' for p in pal) + "</div>"


def swatch(hexcol):
    return f'<span class="sw" style="background:{e(hexcol)}"></span>' if hexcol else '<span class="sw" style="background:repeating-linear-gradient(45deg,transparent 0 3px,#8888 3px 5px)"></span>'


def palette_block(bm, lm, base_label):
    bp = ((bm or {}).get("stats") or {}).get("palette")
    lp = ((lm or {}).get("stats") or {}).get("palette")
    if not bp and not lp:
        return ""
    out = ["<h4>Palette (vertex colours by surface share)</h4>"]
    if bm:
        out.append(f'<div class="sub" style="margin:0">{e(base_label)}</div>{strip(bp)}')
    out.append(f'<div class="sub" style="margin:0">{"Latest" if bm else "This version"}</div>{strip(lp)}')
    rows = G.palette_delta(bp, lp) if bm else None
    if rows:
        moved = [r for r in rows if abs(r["new"] - r["old"]) >= 0.01][:8]
        if moved:
            out.append(f"<table><tr><th>Colour</th><th>{e(base_label)}</th><th>Latest</th></tr>" + "".join(
                f'<tr><td>{swatch(r.get("old_hex") or (r["hex"] if r["old"] else None))}{swatch(r["hex"] if r["new"] else None)}<code>{e(r["hex"])}</code>'
                f'{" new" if not r["old"] else (" gone" if not r["new"] else "")}</td><td class="n">{r["old"] * 100:.1f}%</td><td class="n">{r["new"] * 100:.1f}%</td></tr>' for r in moved) + "</table>")
        else:
            out.append('<p class="sub">The same colours in the same shares (within 1%).</p>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# The comparison


def base_image(home, latest, base, name, shot):
    """The baseline's photograph to show beside the latest: its re-photograph by the latest's
    renderer where there is one, else its own. Returns (rel, same_renderer)."""
    br = latest.get("baseline_render")
    if br and br.get("version") == base["id"]:
        rel = f"{latest['media']}/{br['path']}/{name}/{shot}.jpg"
        if os.path.exists(os.path.join(home, rel)):
            return rel, True
    rel, ok = img_path(home, base, name, shot)
    lr, brr = latest.get("renderer", {}), base.get("renderer", {})
    same = brr.get("key") == lr.get("key") and brr.get("preset") == lr.get("preset")
    return (rel if ok else None), same


def load_cache(path):
    try:
        c = json.load(open(path))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def diff_for(home, latest, base, name, shot, base_rel, cache):
    key = f"{name}/{shot}"
    lat_rel, ok = img_path(home, latest, name, shot)
    if not (ok and base_rel):
        return None, None
    out_rel = f"{latest['media']}/vs/{base['id']}/diff/{name}/{shot}.jpg"
    out = os.path.join(home, out_rel)
    srcs = [os.path.join(home, base_rel), os.path.join(home, lat_rel)]
    c = cache.get(key) or {}
    stale = not os.path.exists(out) or any(os.path.getmtime(s) > os.path.getmtime(out) for s in srcs) or c.get("base") != base_rel or c.get("threshold") != D.THRESHOLD
    if stale:
        r = D.compare(srcs[0], srcs[1], out)
        r.update(base=base_rel, threshold=D.THRESHOLD)
        cache[key] = r
    return out_rel, cache[key]


def change_label(r, same):
    if r is None:
        return ""
    pct = r["changed"] * 100
    cls = "big" if pct >= 5 else ("small" if pct < 0.5 else "")
    note = "" if same else " · renderer differs"
    return f'<span class="chg {cls}">{pct:.1f}% of pixels changed{" (sizes differ)" if r.get("resized") else ""}{note}</span>'


def comparison(home, fam, latest, base, how, up):
    kind = fam["family"].get("kind", "building")
    base_label = {"accepted": "Accepted", "accepted before": "Accepted before", "previous": "Previous"}.get(how, "Accepted")
    out, worst = [], []
    cache_path = os.path.join(home, latest["media"], "vs", base["id"], "diff.json") if base else None
    cache = load_cache(cache_path) if cache_path else {}
    ctrl = controls(latest)
    for m in subjects(latest):
        name = m["name"]
        bm = member(base, name)
        out.append(f'<h3>{e(name)}{" <span class=tag>new in this version</span>" if base and not bm else ""}</h3>')
        out.append(metric_table(bm, m, ctrl, base_label if bm else None))
        out.append(palette_block(bm, m, base_label))
        shots = list(m.get("shots", []))
        key = [s for s in KEY_SHOTS.get(kind, []) if s in shots] or shots[:4]
        rest = [s for s in shots if s not in key]
        rows_key, rows_rest = [], []
        for shot in key + rest:
            lat_rel, _ = img_path(home, latest, name, shot)
            b_rel, same = base_image(home, latest, base, name, shot) if bm else (None, True)
            d_rel, r = diff_for(home, latest, base, name, shot, b_rel, cache) if b_rel else (None, None)
            if r:
                worst.append((r["changed"], f"{name}/{shot}", same))
            figs = []
            if bm:
                figs.append(fig(b_rel, f"<b>{e(base_label)}</b> {e(base['id'])}" + ("" if same or not b_rel else " (another renderer build)"), up=up))
            figs.append(fig(lat_rel, f"<b>Latest</b> {e(latest['id'])} <span class=which></span>", "latest", f'data-latest="{up}{u(lat_rel)}" data-base="{up}{u(b_rel or lat_rel)}"', up))
            if bm:
                figs.append(fig(d_rel, "<b>What changed</b>: red where pixels differ" if d_rel else f"no {e(base_label.lower())} photograph of this shot", up=up))
            for cm in ctrl:
                if shot in cm.get("shots", []):
                    figs.append(fig(img_path(home, latest, cm["name"], shot)[0], f"<b>Target</b>: {e(cm['name'])} (control, this pass)", up=up))
            crop = f"{latest['media']}/{name}/{shot}-crop.png"
            if os.path.exists(os.path.join(home, crop)):
                figs.append(fig(crop, "<b>Latest</b>, the middle of the frame enlarged four times", up=up))
            ncls = {1: "g2", 2: "g2", 3: "g3"}.get(len(figs), "g4")
            btn = ' <button onclick="flicker(this)">Flicker</button>' if b_rel else ""
            row = f'<div class="row"><h4>{e(shot)} {change_label(r, same)}{btn}</h4><div class="grid {ncls}">{"".join(figs)}</div></div>'
            (rows_key if shot in key else rows_rest).append(row)
        out.extend(rows_key)
        if rows_rest:
            out.append(f"<details><summary>{len(rows_rest)} more shots of {e(name)}</summary>{''.join(rows_rest)}</details>")
        for c in m.get("clips", []):
            bc = next((x for x in (bm or {}).get("clips", []) if x["name"] == c["name"]), None)
            vids = []
            if bc:
                vids.append(video(f"{base['media']}/{name}/{bc['file']}", f"<b>{e(base_label)}</b>{' · ' + e(bc['layout']) if bc.get('layout') else ''}", up))
            vids.append(video(f"{latest['media']}/{name}/{c['file']}", f"<b>Latest</b>{' · ' + e(c['layout']) if c.get('layout') else ''}", up))
            for cm in ctrl:
                cc = next((x for x in cm.get("clips", []) if x["name"] == c["name"]), None)
                if cc:
                    vids.append(video(f"{latest['media']}/{cm['name']}/{cc['file']}", f"<b>Target</b>: {e(cm['name'])}", up))
            out.append(f'<div class="row"><h4>clip {e(c["name"])} <button onclick="together(this)">Play together</button></h4><div class="grid g{min(4, max(2, len(vids)))}">{"".join(vids)}</div></div>')
        if bm and bm.get("clips") and not m.get("clips"):
            out.append(f"<details><summary>The {e(base_label.lower())} version's clips</summary><div class='grid g2'>" + "".join(
                video(f"{base['media']}/{name}/{c['file']}", f"<b>{e(c['name'])}</b>{' · ' + e(c['layout']) if c.get('layout') else ''}", up) for c in bm["clips"]) + "</div></details>")
    if base:
        gone = [m["name"] for m in subjects(base) if not member(latest, m["name"])]
        if gone:
            out.append(f'<div class="box warn"><p>In the {e(base_label.lower())} version but not in the latest: {", ".join(e(g) for g in gone)}.</p></div>')
    if latest.get("missing"):
        out.append(f'<div class="box warn"><p>Not photographed in the latest: {e(json.dumps(latest["missing"]))}.</p></div>')
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + f".{os.getpid()}"
        json.dump(cache, open(tmp, "w"), indent=1)
        os.replace(tmp, cache_path)
    return "".join(out), sorted(worst, key=lambda w: -w[0])


def decide_box(name, v):
    return (f'<div class="decidebox" data-family="{e(name)}" data-version="{e(v["id"])}"><div class="decide"><input placeholder="The owner\'s words (optional)">'
            f'<button onclick="decide(this,\'accept\')">Accept</button><button onclick="decide(this,\'reject\')">Reject</button><span class="copied sub"></span></div>'
            f'<textarea class="cmd" rows="2" readonly></textarea></div>')


def family_page(home, fam, standing, baseline_for):
    f = fam["family"]
    name = f.get("family") or f.get("name")
    up = "../"
    last, accepted, _, _ = standing(fam)
    latest_id, base_id, how = baseline_for(fam)
    versions = sorted(fam["versions"].values(), key=lambda v: v.get("published", ""), reverse=True)
    latest = fam["versions"].get(latest_id)
    base = fam["versions"].get(base_id) if base_id else None
    body = [f'<p class="sub"><a href="../index.html">Asset board</a> · {e(f.get("kind", ""))}</p><h1>{e(f.get("title") or name)}</h1>',
            f'<p class="sub"><code>{e(name)}</code>{" · " + e(f["description"]) if f.get("description") else ""}</p>']
    if f.get("target"):
        body.append(f'<div class="box"><p><b>Quality target:</b> {e(f["target"])}</p></div>')
    status = ['<div class="box">']
    if accepted:
        d = last[accepted]
        status.append(f'<p><b>Accepted:</b> <a href="#v-{e(accepted)}">{e(accepted)}</a> on {e(d["date"])}{" as the " + e(d["scope"]) if d.get("scope") else ""}'
                      f'{" by the " + e(d["by"]) if d.get("by") else ""}.</p>')
        if d.get("words"):
            status.append(f'<p>“{e(d["words"])}”</p>')
        if d.get("note"):
            status.append(f'<p class="sub">{e(d["note"])}</p>')
    else:
        status.append("<p><b>Nothing accepted yet.</b></p>")
    if latest and latest_id != accepted:
        status.append(f'<p><b>Latest:</b> <a href="#v-{e(latest_id)}">{e(latest_id)}</a>, published {e(latest.get("published", "")[:16].replace("T", " "))}{" by " + e(latest["maker"]) if latest.get("maker") else ""}'
                      f'{" (" + e(latest["track"]) + ")" if latest.get("track") else ""}: {verdict_tag(last.get(latest_id))}</p>')
        if latest.get("note"):
            status.append(f'<p class="sub">{e(latest["note"])}</p>')
        status.append(decide_box(name, latest))
    status.append("</div>")
    body.append("".join(status))
    worst = []
    if latest:
        if base:
            title = "The accepted version beside the one accepted before it" if how == "accepted before" else f"The latest version beside {HOW.get(how, how)}"
            body.append(f"<h2>{e(title)}</h2><p>{e(base['id'])}: {renderer_line(base)}.<br>{e(latest['id'])}: {renderer_line(latest)}.</p>")
            if latest.get("baseline_render", {}).get("version") == base["id"]:
                body.append(f'<p class="sub">Those models were photographed again by the latest version\'s renderer ({e(latest["renderer"].get("key", ""))}), so the diffs show the models\' change. Their original photographs are in the history below.</p>')
            elif base.get("renderer", {}).get("key") != latest.get("renderer", {}).get("key"):
                body.append('<div class="box warn"><p>The two were photographed by different renderer builds or methods, and the earlier one could not be photographed again (no model file kept, or not made in the game). Some differences may be the renderer\'s.</p></div>')
        else:
            body.append(f"<h2>The latest version</h2><p>{renderer_line(latest)}.</p>")
        comp, worst = comparison(home, fam, latest, base, how, up)
        body.append(comp)
        if latest.get("delivered"):
            body.append("<h3>Delivered with it</h3><ul>" + "".join(f'<li><a href="{up}{u(latest["media"] + "/" + d["path"])}">{e(d["title"])}</a></li>' for d in latest["delivered"]) + "</ul>")
    body.append("<h2>History</h2><table><tr><th>Version</th><th>Published</th><th>Made by</th><th>Source</th><th>Decisions</th><th>Note</th></tr>")
    for v in versions:
        ds = [d for d in fam["decisions"] if d["version"] == v["id"]]
        dec = "<br>".join(f'{verdict_tag(d)}{" “" + e(d["words"]) + "”" if d.get("words") else ""}' for d in ds) or verdict_tag(None)
        body.append(f'<tr id="v-{e(v["id"])}"><td><code>{e(v["id"])}</code>{" <b>(accepted)</b>" if v["id"] == accepted else ""}</td><td>{e(v.get("published", "")[:16].replace("T", " "))}</td>'
                    f'<td>{e(v.get("maker") or "")}{" · " + e(v["track"]) if v.get("track") else ""}</td><td>{source_line(v)}<br><span class="sub">photographed by {renderer_line(v)}</span></td>'
                    f'<td>{dec}</td><td>{e(v.get("note") or "")}</td></tr>')
    body.append("</table>")
    kind = f.get("kind", "building")
    for v in versions:
        thumbs = []
        for m in subjects(v) + controls(v):
            for shot in [s for s in KEY_SHOTS.get(kind, []) if s in m.get("shots", [])][:4] or m.get("shots", [])[:4]:
                rel, ok = img_path(home, v, m["name"], shot)
                if ok:
                    thumbs.append(fig(rel, f"{e(m['name'])}{' (control)' if m.get('role') == 'control' else ''}: {e(shot)}", up=up))
        extra = ""
        if v.get("delivered"):
            extra = "<p>Delivered: " + ", ".join(f'<a href="{up}{u(v["media"] + "/" + d["path"])}">{e(d["title"])}</a>' for d in v["delivered"]) + "</p>"
        allshots = sum(len(m.get("shots", [])) for m in v.get("members", []))
        body.append(f'<details><summary>{e(v["id"])}: {len(v.get("members", []))} model(s), {allshots} photographs</summary>{extra}<div class="thumbs">{"".join(thumbs)}</div>'
                    + "".join(f'<p class="sub">{e(m["name"])}: ' + ", ".join(f"{e(k)} {fmt(x)}" for k, x in list(metrics(m).items())[:8]) + "</p>" for m in v.get("members", [])[:12]) + "</details>")
    return doc(f"{f.get('title') or name}", "".join(body)), worst


def thumb(home, v, kind):
    if not v:
        return None
    for m in subjects(v):
        for shot in THUMB.get(kind, []) + m.get("shots", []):
            rel, ok = img_path(home, v, m["name"], shot)
            if ok:
                return rel
    return None


def write_board(home, families, standing, baseline_for):
    cards = {}
    for name in sorted(families):
        fam = families[name]
        f = fam["family"]
        page, worst = family_page(home, fam, standing, baseline_for)
        s = name.replace(":", "-")
        tmp = os.path.join(home, "family", f".{s}.html.{os.getpid()}")
        with open(tmp, "w") as fh:
            fh.write(page)
        os.replace(tmp, os.path.join(home, "family", s + ".html"))
        last, accepted, _, latest = standing(fam)
        kind = f.get("kind") or name.split(":")[0]
        acc, lat = fam["versions"].get(accepted), fam["versions"].get(latest)
        figs = []
        if acc:
            figs.append(fig(thumb(home, acc, kind), f"<b>Accepted</b> {e(last[accepted]['date'])}"))
        if lat and latest != accepted:
            figs.append(fig(thumb(home, lat, kind), f"<b>Latest</b> {e(lat.get('published', '')[:10])} {verdict_tag(last.get(latest))}"))
        if not figs:
            figs.append(fig(None, "nothing published"))
        lines = [f'<p class="sub" style="margin:0">{len(fam["versions"])} version(s){" · accepted " + e(accepted) if accepted else " · nothing accepted"}</p>']
        if lat and latest != accepted and worst:
            lines.append(f'<p style="margin:2px 0">Most changed: {e(worst[0][1])} {change_label({"changed": worst[0][0]}, worst[0][2])}</p>')
        if acc and last[accepted].get("words"):
            w = last[accepted]["words"]
            lines.append(f'<p class="sub" style="margin:2px 0">“{e(w[:160])}{"…" if len(w) > 160 else ""}”</p>')
        card = (f'<div class="card"><h3><a href="family/{u(s)}.html">{e(f.get("title") or name)}</a></h3><p class="sub" style="margin:0"><code>{e(name)}</code></p>'
                f'<div class="grid g2">{"".join(figs)}</div>{"".join(lines)}</div>')
        cards.setdefault(kind, []).append(card)
    body = [f'<h1>Asset board</h1><p class="sub">Every generated family photographed in the game\'s own renderer in fixed shots, beside the version the owner last accepted. '
            f'Records: <code>living/assets/board/</code> in git. Media: this folder. Written by <code>living/tools/board/board.py</code>; see <code>docs/ASSET_BOARD.md</code>.</p>',
            '<div class="box"><p><b>To decide:</b> open a family, look, and tell a coordinator “accept” or “reject” with your words. The family page writes the command for you; the coordinator runs '
            '<code>python3 living/tools/board/board.py decide FAMILY VERSION accept --words "…"</code>.</p></div>']
    order = ["character", "building", "prop"]
    for kind in sorted(cards, key=lambda k: (order.index(k) if k in order else 9, k)):
        body.append(f"<h2>{e(kind.capitalize())}s</h2><div class='cards'>{''.join(cards[kind])}</div>")
    tmp = os.path.join(home, f".index.html.{os.getpid()}")
    with open(tmp, "w") as fh:
        fh.write(doc("Asset board", "".join(body)))
    os.replace(tmp, os.path.join(home, "index.html"))
