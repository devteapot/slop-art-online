#!/usr/bin/env python3
"""The owner's rating page for blind life excerpts (docs/TRIALS.md, "Owner-tuned player score").

  feel_page.py [--excerpts .local/living/feel/excerpts.json] [--out .local/living/feel/page/player_feel.html]

Reads only the BLIND excerpts file written by feel_excerpts.py (never the key) and writes one
self-contained HTML page: the excerpts in their shuffled order, and per excerpt one question,
"Does this feel like a player living their own life?", on a 1-5 scale with an optional one-line
reason. Published as a claude.ai Artifact with `capabilities: {db: {}, user: {}, downloads: true}`,
each rating is saved server-side as the document `owner_ratings/<excerpt id>`:
`{"score": 1-5, "reason": "...", "at": "<iso>", "rater": "<opaque viewer id>", "source": "page"}`, read
back with the ArtifactData tool (`list` of collection `owner_ratings`) and fed to `feel_tune.py fit
--ratings`. The page never reads or writes the `ratings` collection, where proxy ratings (raters
"proxy:...", someone rating on the owner's behalf) are kept, and it ignores any `proxy:` document it
meets, so the owner always rates blind and never overwrites a proxy rating.
Without the database (a saved copy opened from disk) the page keeps ratings in the browser and
offers "Copy ratings" and "Download ratings.json", which write the same shape feel_tune.py reads.
The page refuses to build if the excerpts file carries anything but ids, titles, intros and lines.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FEEL = REPO / ".local/living/feel"
ALLOWED = {"id", "title", "intro", "lines"}
LINE_KEYS = {"t", "kind", "text"}

TEMPLATE = r"""<title>Player-Feel Ratings</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400&family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column of excerpts like pages of a field log; a quiet sticky tally on top. */
:root {
  --paper: #f3f5f4; --sheet: #ffffff; --ink: #1d2826; --muted: #5f6d69; --rule: #d9e0dd;
  --accent: #1f6f66; --accent-ink: #ffffff; --accent-soft: #dcece9; --said: #12302c; --warn: #9a5b00;
  --serif: "Literata", "Iowan Old Style", Georgia, serif;
  --sans: "Figtree", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #121917; --sheet: #1a2321; --ink: #e3ebe8; --muted: #9aaaa5; --rule: #2c3936;
  --accent: #5cc4b5; --accent-ink: #0d1615; --accent-soft: #1f3532; --said: #f1f7f5; --warn: #e0a54a; color-scheme: dark } }
:root[data-theme="dark"] {
  --paper: #121917; --sheet: #1a2321; --ink: #e3ebe8; --muted: #9aaaa5; --rule: #2c3936;
  --accent: #5cc4b5; --accent-ink: #0d1615; --accent-soft: #1f3532; --said: #f1f7f5; --warn: #e0a54a; color-scheme: dark }
body { background: var(--paper); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.5; }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--paper); }
.wrap { max-width: 760px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 64px; display: grid; gap: 22px; }
header h1 { font-family: var(--serif); font-weight: 600; font-size: 1.9rem; line-height: 1.15; margin: 0 0 8px; text-wrap: balance; }
header p { margin: 0 0 8px; max-width: 65ch; color: var(--muted); }
header p strong { color: var(--ink); font-weight: 600; }
.scale-key { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.85rem; color: var(--muted); margin-top: 6px; }
.scale-key b { font-family: var(--mono); font-weight: 500; color: var(--accent); }
.tally { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--paper); border-bottom: 1px solid var(--rule);
  padding-block: 10px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 0.9rem; }
.bar { flex: 1 1 160px; height: 6px; background: var(--rule); border-radius: 3px; overflow: hidden; min-width: 120px; }
.bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .3s; }
.status { color: var(--muted); font-size: 0.82rem; }
.status.warn { color: var(--warn); }
article { background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; padding: 18px 18px 16px; display: grid; gap: 12px; min-width: 0; }
article.done { border-color: var(--accent); }
article h2 { margin: 0; font-size: 0.78rem; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); font-weight: 600; display: flex; justify-content: space-between; gap: 8px; }
article h2 .mark { color: var(--accent); letter-spacing: .02em; text-transform: none; font-weight: 500; }
.intro { font-family: var(--serif); font-style: italic; color: var(--muted); margin: 0; }
ol.log { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-family: var(--serif); font-size: 0.97rem; line-height: 1.5; }
ol.log li { display: grid; grid-template-columns: 3.4em 1fr; gap: 10px; min-width: 0; }
ol.log time { font-family: var(--mono); font-size: 0.74rem; color: var(--muted); padding-top: 0.28em; font-variant-numeric: tabular-nums; }
ol.log span { min-width: 0; overflow-wrap: anywhere; }
li.said span { color: var(--said); font-weight: 600; }
li.heard span { font-style: italic; }
li.plan span { color: var(--accent); }
li.did span, li.saw span { color: var(--muted); }
li.body { margin-top: 4px; padding-top: 8px; border-top: 1px dashed var(--rule); }
li.body span { font-family: var(--sans); font-size: 0.86rem; color: var(--muted); }
.q { display: grid; gap: 8px; padding-top: 10px; border-top: 1px solid var(--rule); }
.q > p { margin: 0; font-weight: 600; }
.scale { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
.scale button { font: 600 1rem var(--mono); padding: 9px 0; border: 1px solid var(--rule); border-radius: 5px; background: var(--paper); color: var(--ink); cursor: pointer; }
.scale button:hover { border-color: var(--accent); }
.scale button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.scale button:focus-visible, input:focus-visible, .tools button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.ends { display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--muted); gap: 8px; }
.q input { width: 100%; box-sizing: border-box; font: inherit; padding: 8px 10px; border: 1px solid var(--rule); border-radius: 5px; background: var(--paper); color: var(--ink); }
footer { display: grid; gap: 10px; }
footer h2 { font-family: var(--serif); font-weight: 600; font-size: 1.2rem; margin: 0; }
footer p { margin: 0; color: var(--muted); max-width: 65ch; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; }
.tools button { font: 600 0.9rem var(--sans); padding: 8px 14px; border-radius: 5px; border: 1px solid var(--accent); background: var(--accent-soft); color: var(--ink); cursor: pointer; }
textarea { width: 100%; box-sizing: border-box; min-height: 120px; font: 0.78rem var(--mono); background: var(--sheet); color: var(--ink); border: 1px solid var(--rule); border-radius: 5px; padding: 8px; }
@media (prefers-reduced-motion: reduce) { .bar i { transition: none; } }
</style>
<div class="wrap">
  <header>
    <h1>Does this feel like a player living their own life?</h1>
    <p>Below are <strong id="count">__N__ short excerpts</strong> from the lives of characters in the world. Each covers about __W__ minutes of play, told from the character's side: what they noticed, said and did. The order is shuffled and nothing on the page says where an excerpt came from.</p>
    <p>For each one, pick a number and, if you like, say why in a line. Every click is saved as you go, so you can stop and come back.</p>
    <div class="scale-key"><span><b>1</b> an NPC getting by</span><span><b>3</b> could go either way</span><span><b>5</b> clearly a player living their own life</span></div>
  </header>
  <div class="tally" role="status"><span id="done">0 of __N__ rated</span><div class="bar" aria-hidden="true"><i id="fill"></i></div><span class="status" id="store">Connecting to saved ratings…</span></div>
  <main id="list" style="display:grid;gap:22px"></main>
  <footer>
    <h2>When you are done</h2>
    <p id="done-note">Your ratings are saved with this page; nothing else to do. If saving is unavailable here, copy or download them and send the file back.</p>
    <div class="tools"><button type="button" id="copy">Copy ratings</button><button type="button" id="dl">Download ratings.json</button></div>
    <textarea id="dump" readonly hidden aria-label="Ratings as JSON"></textarea>
  </footer>
</div>
<script>
const EXCERPTS = __DATA__;
const N = EXCERPTS.length;
const state = {};          // id -> {score, reason, at}
let db = null, uid = null, saving = {}, uploaded = false;
const COLL = "owner_ratings";            // never "ratings": the proxy's ratings live there
const LS = "player-feel-owner-ratings";  // a new key, so nothing stored by an earlier version shows as rated
function lsLoad() { try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) { return {}; } }
function lsSave() { try { localStorage.setItem(LS, JSON.stringify(state)); } catch (e) {} }
Object.assign(state, lsLoad());

const list = document.getElementById("list");
function el(tag, attrs, text) { const e = document.createElement(tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; }

EXCERPTS.forEach((x) => {
  const a = el("article", {id: "x-" + x.id});
  const h = el("h2"); h.append(el("span", {}, x.title)); const mark = el("span", {class: "mark"}); h.append(mark); a.append(h);
  if (x.intro) a.append(el("p", {class: "intro"}, x.intro));
  const ol = el("ol", {class: "log"});
  x.lines.forEach((l) => { const li = el("li", {class: l.kind}); li.append(el("time", {}, l.t || "")); li.append(el("span", {}, l.text)); ol.append(li); });
  a.append(ol);
  const q = el("div", {class: "q"});
  q.append(el("p", {id: "q-" + x.id}, "Does this feel like a player living their own life?"));
  const sc = el("div", {class: "scale", role: "group", "aria-labelledby": "q-" + x.id});
  for (let v = 1; v <= 5; v++) {
    const b = el("button", {type: "button", "aria-pressed": "false", id: "s-" + x.id + "-" + v}, String(v));
    b.addEventListener("click", () => { setRating(x.id, v, null); });
    sc.append(b);
  }
  q.append(sc);
  const ends = el("div", {class: "ends"}); ends.append(el("span", {}, "1 an NPC getting by")); ends.append(el("span", {}, "5 a player living their own life")); q.append(ends);
  const inp = el("input", {type: "text", id: "r-" + x.id, maxlength: "240", placeholder: "Why? (optional, one line)", "aria-label": "Reason for " + x.title});
  let tm = null;
  inp.addEventListener("input", () => { clearTimeout(tm); tm = setTimeout(() => { if ((state[x.id]?.reason || "") !== inp.value.trim().slice(0, 240)) setRating(x.id, null, inp.value); }, 900); });
  inp.addEventListener("blur", () => { clearTimeout(tm); if ((state[x.id]?.reason || "") !== inp.value.trim().slice(0, 240)) setRating(x.id, null, inp.value); });
  q.append(inp);
  a.append(q);
  list.append(a);
});

function paint() {
  let n = 0;
  EXCERPTS.forEach((x) => {
    const r = state[x.id] || {};
    const a = document.getElementById("x-" + x.id);
    for (let v = 1; v <= 5; v++) document.getElementById("s-" + x.id + "-" + v).setAttribute("aria-pressed", r.score === v ? "true" : "false");
    const inp = document.getElementById("r-" + x.id);
    if (document.activeElement !== inp && (r.reason || "") !== inp.value) inp.value = r.reason || "";
    const ok = Number.isInteger(r.score);
    a.classList.toggle("done", ok);
    a.querySelector(".mark").textContent = ok ? (saving[x.id] ? "saving…" : "rated " + r.score) : "";
    if (ok) n++;
  });
  document.getElementById("done").textContent = n + " of " + N + " rated";
  document.getElementById("fill").style.width = (100 * n / N) + "%";
  if (n === N) document.getElementById("done-note").textContent = "All " + N + " rated. Thank you; they are saved with this page. Copy or download them only if saving is unavailable here.";
}

function status(text, warn) { const s = document.getElementById("store"); s.textContent = text; s.classList.toggle("warn", !!warn); }

function setRating(id, score, reason) {
  const cur = Object.assign({}, state[id] || {});
  if (score != null) cur.score = score;
  if (reason != null) cur.reason = reason.trim().slice(0, 240);
  cur.at = new Date().toISOString();
  state[id] = cur; lsSave(); paint();
  push(id);
}

// One write at a time per rating; a change made while one is in flight is sent when it lands.
const inflight = {}, dirty = {};
async function push(id) {
  if (!db || !Number.isInteger((state[id] || {}).score)) return; // a reason alone waits for its score
  if (inflight[id]) { dirty[id] = true; return; }
  inflight[id] = true; saving[id] = true; paint();
  try {
    do {
      dirty[id] = false;
      const cur = state[id];
      const body = {score: cur.score, reason: cur.reason || "", at: cur.at, source: "page"};
      if (uid) body.rater = uid;
      try {
        await db.collection(COLL).doc(id).set(body);
        status("Saved with this page");
      } catch (e) {
        if (e && e.code === "unavailable") {
          await new Promise(r => setTimeout(r, 600 + Math.random() * 600));
          try { await db.collection(COLL).doc(id).set(body); status("Saved with this page"); }
          catch (e2) { status("Could not save just now; your choice is kept in this browser. Use Copy ratings at the bottom.", true); }
        } else {
          status("Saving is not available to you here; your choices stay in this browser. Use Copy ratings at the bottom.", true);
          db = null;
        }
      }
    } while (dirty[id] && db);
  } finally { inflight[id] = false; saving[id] = false; paint(); }
}

function exportJson() {
  const ratings = {};
  EXCERPTS.forEach((x) => { const r = state[x.id]; if (r && Number.isInteger(r.score)) ratings[x.id] = {score: r.score, reason: r.reason || "", at: r.at}; });
  return JSON.stringify({synthetic: false, rater: "owner (rating page)", page: "player-feel ratings", ratings: ratings}, null, 1);
}
document.getElementById("copy").addEventListener("click", () => {
  const t = exportJson(); const d = document.getElementById("dump");
  d.value = t; d.hidden = false;
  try { navigator.clipboard.writeText(t).then(() => status("Ratings copied"), () => { d.select(); status("Select the text below and copy it", true); }); }
  catch (e) { d.select(); status("Select the text below and copy it", true); }
});
document.getElementById("dl").addEventListener("click", async () => {
  const t = exportJson();
  const dls = window.claude ? await window.claude.use("downloads").catch(() => null) : null;
  if (dls) { try { await dls.save({filename: "ratings.json", data: t}); return; } catch (e) {} }
  const d = document.getElementById("dump"); d.value = t; d.hidden = false; d.select();
  status("Download is not available here; copy the text below instead", true);
});

paint();
(async () => {
  if (!window.claude || !window.claude.use) { status("Saving with the page is unavailable here; choices stay in this browser", true); return; }
  const timer = setTimeout(() => status("Saved ratings can't be reached yet; your choices are kept in this browser", true), 10000);
  const [d, u] = await Promise.all([window.claude.use("db").catch(() => null), window.claude.use("user").catch(() => null)]);
  if (u) { try { uid = await u.id(); } catch (e) {} }
  if (!d) { clearTimeout(timer); status("Saving with the page is unavailable here; choices stay in this browser", true); return; }
  db = d;
  db.collection(COLL).onSnapshot((snap) => {
    clearTimeout(timer);
    if (!db) return; // saving was refused earlier in this visit: keep the warning
    snap.docs.forEach((doc) => {
      const v = doc.data() || {};
      if (!EXCERPTS.some((x) => x.id === doc.id) || !Number.isInteger(v.score)) return;
      if (String(v.rater || "").startsWith("proxy:") || v.proxy_for) return; // someone rating for the owner: never shown
      const mine = state[doc.id];
      if (!mine || !mine.at || (v.at && v.at >= mine.at)) state[doc.id] = {score: v.score, reason: v.reason || "", at: v.at};
    });
    lsSave(); paint();
    if (!snap.metadata.fromCache) {
      status("Saved with this page");
      // Choices made in this browser before saving was reachable go up once, after the first full read.
      if (!uploaded) {
        uploaded = true;
        const pending = EXCERPTS.filter((x) => { const r = state[x.id]; const remote = snap.docs.find((doc) => doc.id === x.id);
          return r && Number.isInteger(r.score) && (!remote || ((remote.data() || {}).at || "") < (r.at || "")); });
        setTimeout(async () => { for (const x of pending) await push(x.id); }, 0);
      }
    }
  }, (e) => { clearTimeout(timer); status("Saved ratings can't be reached; your choices are kept in this browser", true); db = null; });
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--excerpts", default=str(FEEL / "excerpts.json"))
    ap.add_argument("--out", default=str(FEEL / "page/player_feel.html"))
    a = ap.parse_args()
    doc = json.loads(Path(a.excerpts).expanduser().read_text())
    ex = doc["excerpts"]
    for e in ex:
        extra = set(e) - ALLOWED
        if extra or any(set(l) - LINE_KEYS for l in e["lines"]):
            sys.exit(f"refusing: excerpt {e.get('id')} carries fields beyond the blind ones: {sorted(extra)}")
        if not re.fullmatch(r"[a-z0-9]{3,12}", e["id"]):
            sys.exit(f"refusing: excerpt id {e['id']!r} is not an opaque token")
    data = json.dumps(ex, ensure_ascii=False).replace("</", "<\\/")
    words = {5: "five", 10: "ten", 15: "fifteen", 20: "twenty"}
    w = doc.get("window_min", 10)
    page = TEMPLATE.replace("__DATA__", data).replace("__N__", str(len(ex))).replace("__W__", words.get(w, f"{w:g}"))
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"{len(ex)} excerpts -> {out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
