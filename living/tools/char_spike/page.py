#!/usr/bin/env python3
"""Spike (branch char-spike): write the comparison page from media.py's output.

    python3 living/tools/char_spike/page.py PAGE_DIR [--finished "HH:MM"] [--head SHA]

PAGE_DIR holds img/, clips/ and stats.json (media.py). Writes PAGE_DIR/index.html, which refers to
them by relative paths, so the folder can be moved or packed as it is.
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
main { max-width:1240px; margin:0 auto; padding:24px 16px 80px; }
h1 { font-size:30px; line-height:1.2; margin:8px 0 4px; }
h2 { font-size:22px; margin:44px 0 10px; padding-top:14px; border-top:1px solid var(--line); }
h3 { font-size:17px; margin:22px 0 6px; }
p, li { max-width:78ch; }
.sub { color:var(--mute); margin:0 0 18px; }
.verdict { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--accent); padding:14px 18px; border-radius:6px; margin:18px 0; }
.verdict p { margin:6px 0; }
.grid { display:grid; gap:10px; margin:10px 0 6px; }
.g2 { grid-template-columns:repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns:repeat(3, minmax(0, 1fr)); }
.g4 { grid-template-columns:repeat(4, minmax(0, 1fr)); } .g6 { grid-template-columns:repeat(6, minmax(0, 1fr)); }
@media (max-width:760px) { .g3, .g4, .g6 { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:6px; overflow:hidden; }
figure img, figure video { display:block; width:100%; height:auto; }
figcaption { padding:6px 10px 8px; font-size:13.5px; color:var(--mute); }
figcaption b { color:var(--fg); }
table { border-collapse:collapse; margin:10px 0; font-size:14.5px; display:block; overflow-x:auto; max-width:100%; }
th, td { border:1px solid var(--line); padding:5px 10px; text-align:left; vertical-align:top; }
th { background:var(--card); } td.n { text-align:right; font-variant-numeric:tabular-nums; }
code { font:13.5px ui-monospace, SFMono-Regular, Menlo, monospace; background:var(--card); border:1px solid var(--line); border-radius:4px; padding:0 4px; }
.cols { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:0 28px; } @media (max-width:760px) { .cols { grid-template-columns:1fr; } }
.weak li b { color:var(--bad); } .ok li b { color:var(--good); }
.labels { display:grid; grid-template-columns:1fr 1fr; font-size:13.5px; color:var(--mute); padding:6px 10px 0; } .labels b { color:var(--fg); }
.lineup { display:flex; align-items:flex-end; gap:6px; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:10px; overflow-x:auto; }
.lineup figure { border:0; flex:0 0 auto; background:none; } .lineup img { width:auto; }
"""


def fig(src, cap, cls=""):
    return f'<figure class="{cls}"><img loading="lazy" src="{src}" alt="{html.escape(cap, quote=True)}"><figcaption>{cap}</figcaption></figure>'


def video(src, cap):
    return (f'<figure><div class="labels"><span><b>Ours</b> (scripted)</span><span><b>VRoid</b> (Sendagaya Shino)</span></div>'
            f'<video src="{src}" controls loop muted autoplay playsinline></video><figcaption>{cap}</figcaption></figure>')


def trio(shot, caps, who=("ours", "vroid", "vroid-smith")):
    names = {"ours": "<b>Ours</b>: scripted man", "vroid": "<b>VRoid</b>: Sendagaya Shino, unchanged", "vroid-smith": "<b>VRoid as a man today</b>: the <code>smith</code> recipe on Shino"}
    return '<div class="grid g3">' + "".join(fig(f"img/{w}-{shot}.jpg", names[w] + (". " + caps if caps and w == "ours" else "")) for w in who) + "</div>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("--finished", default="")
    ap.add_argument("--head", default="")
    a = ap.parse_args()
    st = json.load(open(os.path.join(a.page, "stats.json")))
    o, v = st["ours"], st["vroid"]
    have = lambda f: os.path.exists(os.path.join(a.page, f))
    kib = lambda b: f"{b / 1024:,.0f} KiB"

    def parts_row(s):
        return ", ".join(f"{k} {n:,}" for k, n in sorted(s["parts"].items(), key=lambda x: -x[1]))

    variants = [(k, cap) for k, cap in (
        ("ours", "The man (1.80 m)"), ("heavy", "Recipe only: heavier build, taller, other skin, hair and coat colours on the same file"),
        ("elder", "Generator: receded hair, lines, grey beard, flat cap, tarred coat"), ("woman", "Generator: her own torso, softer face, kerchief, smock and apron"),
        ("lad", "Generator: no beard, no coat, younger face"), ("boy", "Recipe on the lad's file: child proportions, 1.24 m"),
    ) if have(f"img/{k}-front.jpg")]
    heights = {"ours": 1.80, "heavy": 1.88, "elder": 1.72, "woman": 1.66, "lad": 1.70, "boy": 1.24}

    body = f"""
<h1>Can the game's characters come wholly from our own Blender scripts?</h1>
<p class="sub">Spike for decision 2 of <code>docs/SMALL_CITY.md</code> · branch <code>char-spike</code>{' @ ' + a.head if a.head else ''} · dev-box, 2026-11-11 · every picture and clip below is the game's own renderer (<code>living/tools/view_assets.sh</code>)</p>

<div class="verdict">
<p><b>Verdict: replace VRoid for Cullet's residents, knowing the faces will be plainer.</b></p>
<p>One script, <code>living/tools/blender/person.py</code>, now builds a whole adult man (body form, face, hands with fingers, hair, beard, jersey, patched oilskin coat, trousers, sea boots) with no VRoid base, no downloaded mesh and no texture, and the existing pipeline animates and shades him unchanged. The same script drew a first-pass cast of 64 from seeds in three minutes (section 7).</p>
<p>In the close face shot he loses to the VRoid sample clearly: its face and hair are a class above. At the game camera that difference is not visible, and he is a man of Cullet, which the VRoid bases cannot give without the owner making new bases by hand.</p>
<p>If the close face shot matters more than independence, the fallback is the middle option: keep VRoid bases and generate only hair and outfits. Staying as we are is the one option the pictures argue against: see the third column.</p>
</div>

<h2>1. Stills, side by side</h2>
<p>The same camera for each column. The pose is the library's <code>idle</code> at 1.0 s. The third column is how a man is made from the VRoid bases today (option B of decision 2): the <code>smith</code> recipe stretches and recolours Shino.</p>
<h3>Front</h3>
{trio("front", "")}
<h3>Three-quarter</h3>
{trio("three-quarter", "")}
<h3>The game camera (22 m, 28° down), whole frame at 1600×900</h3>
{trio("game", "")}
<p>At this distance a character is about 35 pixels tall. The same frames, the middle 200×150 pixels enlarged four times without smoothing:</p>
<div class="grid g3">{"".join(fig(f"img/{w}-game-crop.png", c) for w, c in (("ours", "<b>Ours</b>"), ("vroid", "<b>VRoid</b>"), ("vroid-smith", "<b>VRoid as a man today</b>")))}</div>
<h3>Close face</h3>
{trio("face", "")}
{trio("face-three-quarter", "")}
{trio("face-side", "")}

<h2>2. Clips, the same frames for both</h2>
<p>Both characters play the same cached Kimodo takes, retargeted by <code>animate.py</code> with no change to it. Frames are poses held at fixed times, so VRoid's spring bones (hair, skirt) rest here; in play they swing, and ours has none.</p>
<div class="grid g2">
{video("clips/idle-tq.mp4", "<b>idle</b>, 4 s at 12 fps")}
{video("clips/sword_slash-tq.mp4", "<b>sword_slash</b> (one strike), 15 fps; there is no weapon prop in either")}
{video("clips/walk-tq.mp4", "<b>walk</b>, the loop four times")}
{video("clips/walk-side.mp4", "<b>walk</b> from the side")}
{video("clips/run-tq.mp4", "<b>run</b>, the loop six times")}
{video("clips/run-side.mp4", "<b>run</b> from the side")}
{video("clips/sit_down-tq.mp4", "<b>sit_down</b>: sitting exists in the cache (sit_down, sit_idle, stand_up)")}
{video("clips/sit_idle-tq.mp4", "<b>sit_idle</b>, 2 s. The takes recline as if against a backrest (a known flaw of the library)")}
</div>

<h2>3. Looked at hard</h2>
<h3>Hands</h3>
<div class="grid g2">{fig("img/ours-hands.jpg", "<b>Ours</b>, <code>talk</code> at 2.0 s. Five fingers on three bones each, two rings round every joint; they curl with the clip. No nails, no knuckles, and the fingers are tubes pushed into the palm, not grown from it.")}{fig("img/vroid-hands.jpg", "<b>VRoid</b>, the same frame.")}</div>
<h3>Shoulder and elbow</h3>
<div class="grid g4">{fig("img/ours-shoulder.jpg", "<b>Ours</b>, <code>wave</code> at 1.4 s")}{fig("img/vroid-shoulder.jpg", "<b>VRoid</b>")}{fig("img/ours-elbow.jpg", "<b>Ours</b>, <code>sword_slash</code> at 1.25 s")}{fig("img/vroid-elbow.jpg", "<b>VRoid</b>")}</div>
<h3>Hip and knee</h3>
<div class="grid g4">{fig("img/ours-hip.jpg", "<b>Ours</b>, <code>sit_idle</code>: the coat's front follows the thighs, its back hangs through the seat, the hands sink into the lap")}{fig("img/vroid-hip.jpg", "<b>VRoid</b>: the skirt is rigid and the thighs pass through it")}{fig("img/ours-knee.jpg", "<b>Ours</b>, <code>run</code> at 0.2 s")}{fig("img/vroid-knee.jpg", "<b>VRoid</b>")}</div>
<h3>Sitting</h3>
<div class="grid g4">{fig("img/ours-sit-three-quarter.jpg", "<b>Ours</b>")}{fig("img/vroid-sit-three-quarter.jpg", "<b>VRoid</b>")}{fig("img/ours-sit-side.jpg", "<b>Ours</b>")}{fig("img/vroid-sit-side.jpg", "<b>VRoid</b>")}</div>
{'<h3>Blink and mouth</h3><p>The eyes, lashes, brows and mouth are one mesh with two morph targets under the names the game already drives for VRoid faces (<code>Fcl_EYE_Close</code>, <code>Fcl_MTH_A</code>). The game log reports <code>rigged a VRoid model (13 bones, face found)</code> for our file. These frames are from the game with its procedural blink and talking mouth running:</p><div class="grid g4">' + "".join(fig(f"img/{f}", c) for f, c in (("ours-blink-open.jpg", "Open"), ("ours-blink-shut.jpg", "A blink"), ("ours-mouth-open.jpg", "The mouth open while talking")) if have("img/" + f)) + '</div>' if have("img/ours-blink-shut.jpg") or have("img/ours-mouth-open.jpg") else ''}

<h2>4. Level of detail reached</h2>
<table>
<tr><th></th><th>Ours (scripted man)</th><th>VRoid (Sendagaya Shino)</th></tr>
<tr><td>Triangles</td><td class="n">{o['triangles']:,}</td><td class="n">{v['triangles']:,}</td></tr>
<tr><td>Vertices in the file</td><td class="n">{o['vertices']:,}</td><td class="n">{v['vertices']:,}</td></tr>
<tr><td>Triangles by part</td><td>{parts_row(o)}</td><td>{parts_row(v)}</td></tr>
<tr><td>Skeleton</td><td>{o['bip_bones']} <code>J_Bip</code> bones (the same names and T-pose, identity rest rotations) under a <code>Root</code>; no spring bones</td><td>{v['bip_bones']} <code>J_Bip</code> bones, {v['spring_bones']} spring bones in {v['spring_groups']} groups (hair, skirt, bust)</td></tr>
<tr><td>Skin weights</td><td>Written ring by ring in the script (no automatic weights), at most four bones a vertex</td><td>VRoid Studio's</td></tr>
<tr><td>Colour</td><td>Vertex colours only (COLOR_0 per face corner) on {len(o['materials'])} white materials; <b>{o['textures']} textures</b>. Soft shade is painted into the colours by the script: how closed-in each vertex is in the rest pose (under the collar, inside cuffs, under the coat's skirt), and a slow mottle on cloth</td><td>{v['textures']} textures, {kib(v['texture_bytes'])}, on {len(v['materials'])} materials</td></tr>
<tr><td>Face</td><td>Skin with flattened normals and a shadow map from <code>face_normals.py</code>, unchanged; eyes, lashes, brows and mouth as thin shells; {o['morph_targets']} morph targets (blink, mouth open)</td><td>The same shading; {v['morph_targets']} morph targets (expressions and visemes)</td></tr>
<tr><td>File</td><td class="n">{kib(o['bytes'])} with {len(o['clips'])} clips</td><td class="n">{kib(v['bytes'])} with {len(v['clips'])} clips</td></tr>
<tr><td>Made by</td><td><code>person.py</code>, about 5 s in Blender 5.2 (most of it the painted shade), then <code>animate.py</code>, <code>merge_primitives.py</code>, <code>face_normals.py</code> as for any base (about 5 s)</td><td>A person in VRoid Studio (a GUI); the two CC0 samples are both young women</td></tr>
</table>
<p>How ours is modelled: the head is a cube-sphere projected onto a signed distance field (cranium, jaw, chin, cheekbones, brow, nose, lips), denser toward the face. Torso, arms, legs, boots and every garment are low cages lofted from rings and subdivided once, so elbows, knees and the shoulder have proper edge loops. Garments are the body's form plus an offset and share its weights, so layers do not poke through each other. Hair is a cap and about forty tapered clumps that follow the head. The beard, the kerchief and the cap are the head's own quads pushed out, with their edge snapped to a smooth line.</p>
<p>Skin exists only where it shows (head, neck, hands). Under the clothes there is the form the garments are offsets of, not a mesh; <code>person.py --body</code> builds it for inspection.</p>

<h2>5. What is weak</h2>
<div class="cols">
<ul class="weak">
<li><b>The face is plain.</b> Flat skin, simple eyes with one highlight, a line for a mouth. Next to the VRoid sample it reads as a toy figure in the close shot. Two morph targets against VRoid's {v['morph_targets']}: no smile, no anger, no visemes.</li>
<li><b>The hair is a helmet of clumps.</b> No strands, no fine edge. In profile the side clumps read as flat planks. It does not move: there are no spring bones.</li>
<li><b>The clothes have no folds.</b> Colour changes only face by face, so large areas are flat. Patches and ribbing are colour, not cloth. Nothing drapes or swings; the coat is stiff.</li>
<li><b>Sitting breaks the coat.</b> Its back hangs through where a seat would be, and hands rest inside the lap. VRoid's skirt fails the same way; neither is solved.</li>
</ul>
<ul class="weak">
<li><b>The hands are simple.</b> Finger tubes intersect the palm; no nails or knuckles.</li>
<li><b>The beard is a shell.</b> From the side it is a smooth mask with a hard edge.</li>
<li><b>The neck and face shade differently.</b> The face takes the game's face shadow map and the neck does not, so a line shows under the jaw. VRoid files have the same seam, hidden by hair and collars.</li>
<li><b>Women, elders and children are first passes</b> (section 7). They prove the levers work, not that the cast is done. Their faces are the weakest part of the whole spike.</li>
<li><b>Not measured:</b> frame cost in a crowd. The triangle count is below VRoid's and the materials share by content as VRoid's do, but no crowd was run.</li>
</ul>
</div>
<h3>What holds up</h3>
<ul class="ok">
<li><b>The pipeline took it unchanged.</b> <code>animate.py</code> retargeted and grafted the clips with 0.0000° error on the first try; <code>face_normals.py</code>, <code>merge_primitives.py</code>, the recipe system (height, proportions, recolouring) and the toon shading kinds all work from the material names and skeleton conventions.</li>
<li><b>Deformation is clean</b> at elbows, knees and shoulders, because the loops and weights are written, not guessed.</li>
<li><b>He belongs to Cullet.</b> Every colour is from the palette in <code>docs/SMALL_CITY.md</code>; the silhouette (collar, coat skirt, folded sea boots) reads at the game camera.</li>
</ul>

<h2>6. Time and attempts</h2>
<table>
<tr><th>When (dev-box clock)</th><th>What</th></tr>
<tr><td>13:15</td><td>Start: reading the pipeline (<code>animate.py</code>, <code>characters.rs</code>, <code>lookdev.rs</code>, <code>view.rs</code>, <code>face_normals.py</code>).</td></tr>
<tr><td>13:20–13:25</td><td>Release build of the game (2.5 min). The VRoid control animated from the cache and photographed.</td></tr>
<tr><td>13:32</td><td><b>Attempt 1.</b> First run of <code>person.py</code>: a whole man, already through <code>animate.py</code> and the game. Hair like sausages, blotchy face, small eyes, thin hands.</td></tr>
<tr><td>13:37</td><td><b>Attempt 2.</b> Head 8% larger, larger eyes, heavier brows, a nose line, hair as flat clumps, larger hands, wider boots, the coat's front following the thighs.</td></tr>
<tr><td>13:39–13:41</td><td><b>Attempt 3.</b> A beard (two designs failed: a strap-like shell that the chin poked through, then a mouth floating in front of it), coat buttons.</td></tr>
<tr><td>13:43</td><td><b>Attempt 4.</b> The boots had been inside-out since attempt 1 (Blender's normal recalculation guessed wrong on an open tube): what looked like a blurry outline and a claw toe. Fixed with an orientation rule per piece.</td></tr>
<tr><td>13:45</td><td><b>Attempt 5.</b> The beard rebuilt from the face's own quads; the boot's folded top as its own band.</td></tr>
<tr><td>13:50–13:58</td><td>Variants: woman, elder, lad, and recipes for a boy and a heavy man.</td></tr>
<tr><td>14:00</td><td><b>Attempt 6.</b> Broader shoulders, calmer eyes, blink and mouth morph targets.</td></tr>
<tr><td>14:20</td><td><b>Attempt 7.</b> Shade painted into the vertex colours and a mottle on cloth, because the clothes were flat.</td></tr>
<tr><td>14:21–14:27</td><td>Seeded residents: 64 files built, animated and photographed in 3 minutes on six cores, then re-photographed twice to fix the sheets.</td></tr>
<tr><td>14:30</td><td><b>Attempt 8</b> (the one shown). One pass on the faces after seeing the 64 together: the upper lid over the top of the iris (a full disc stares), a second highlight, larger and lower eyes for women and children, an upper lip where lips are tinted. Then everything was built and photographed again.</td></tr>
<tr><td>{a.finished or '…'}</td><td>Captures, this page.</td></tr>
</table>
<p><b>About an hour from the first run to the man shown, in eight attempts, by one agent session</b>; the first half hour got him most of the way, and much of the rest went to the variants and the cast. The whole spike, reading and page included, took well under the half day allowed. That speed is the main finding besides the pictures: a new person or garment is a change to a script and a 7-second rebuild, judged in the game's renderer. What it does not buy is taste. The remaining weaknesses are not bugs to grind through; they need someone to say what a Cullet face should look like.</p>

<h2>7. How 64 residents would vary</h2>
<p>Three levers, all exercised in this spike. Each figure below is at its recipe's height.</p>
<div class="lineup">{"".join(f'<figure><img loading="lazy" style="height:{int(430 * heights[k] / 1.88)}px" src="img/{k}-front.jpg" alt=""><figcaption style="max-width:{int(430 * heights[k] / 1.88)}px">{html.escape(c)}</figcaption></figure>' for k, c in variants)}</div>
<div class="grid g6">{"".join(fig(f"img/{k}-face.jpg", html.escape(c.split(':')[0].split(' (')[0])) for k, c in variants)}</div>
<table>
<tr><th>Lever</th><th>What it changes</th><th>Cost</th><th>State after this spike</th></tr>
<tr><td><b>The generator's numbers</b> (<code>VARIANTS</code> in <code>person.py</code>)</td><td>The torso's cross-sections (a woman's waist, hips and chest), limb girth, the face's jaw, chin, brow, nose and lips, eye size, lashes and brows, age lines, hairline, stubble, skin, hair and eye colours</td><td>A dictionary entry or a seed; 5 s to build, 5 s to animate</td><td>Works. Four named entries (man, youth, elder, woman) and seeded residents of six kinds. Everything but the man is a first pass: the faces differ too little.</td></tr>
<tr><td><b>Garments and hair</b> (functions in <code>person.py</code>)</td><td>Jersey, open coat with patches, pull-over smock (short, or to the knee with an apron), trousers, sea boots; beard; flat cap, kerchief; six hair layouts (tousled, short, sides under a cap, a fringe under a kerchief, two bobs)</td><td>A new garment is 20 to 60 lines on the shared rings; it inherits weights</td><td>Of the plan's <code>cullet</code> set: jersey, oilskin smock, patched coat, sea boots, flat cap and headscarf exist. Missing: leather apron, clogs, shawl, hair longer than a bob. The flat cap is too low to read as one.</td></tr>
<tr><td><b>The game's recipes</b> (<code>recipes.json</code>, unchanged code)</td><td>Height, proportions (legs, arms, torso, head, shoulders, hips, build, hands, feet), and colours by slot: hair, eyes, skin, jersey, trousers, boots, coat</td><td>A JSON entry, no build</td><td>Works on our files as on VRoid's: the heavy man and the boy above are recipes only. Children are an adult file with child proportions, as the small folk already are.</td></tr>
</table>
<h3>A seeded cast of 64</h3>
<p>The residents' sheets do not exist yet, so this is not Cullet's cast. It is 64 people drawn from seeds in the cast's numbers (<code>docs/SMALL_CITY.md</code> §3: 50 adults, 6 of them elders, and 14 children): 22 men, 22 women, 3 old men, 3 old women, 7 boys, 7 girls. Each is its own file (<code>person.py --variant &lt;seed&gt;:&lt;kind&gt;</code>) with its own recipe for height and, for children, proportions by age. Nobody has looked at them one by one or tuned them: this is what the generator gives unreviewed. One scale for all, from the front, 24° down.</p>
{fig("img/cast-lineup.jpg", "Rows: 16 men; 6 men, 3 old men, 7 boys; 16 women; 6 women, 3 old women, 7 girls. Open the image for full size (3248 px wide).") if have("img/cast-lineup.jpg") else ""}
<p>Their faces, in the same order:</p>
{fig("img/cast-faces.jpg", "The same 64, close. This is where the approach is weakest: the faces differ by skin, hair, beard and lines, but the features are one face with small changes, and the women's and children's faces are blank.") if have("img/cast-faces.jpg") else ""}
<p>What the line-up shows: at the distance the game is played, the cast reads as one village with enough variety in build, age, hair, headwear and dress. What it also shows: every stance is the same clip, garments are few (coat, smock, jersey, apron, cap, kerchief), and the faces need a person's eye. With the sheets, each resident would get a line of numbers instead of a seed, and household colours.</p>

<h2>8. What the three options cost</h2>
<table>
<tr><th>Option</th><th>What you get</th><th>What it costs</th></tr>
<tr><td><b>Replace VRoid</b> (recommended)</td><td>Men, women, elders and children of Cullet from one script, in the palette, with no GUI and no owner hand-work. Every change is a rebuild.</td><td>Plainer faces and hair than VRoid's, for good unless someone art-directs them. My estimate to bring the cast to the man's level and close the gaps that matter in play: two to three days (women's and children's forms and faces, long hair, the rest of the garment set, more expressions and visemes, spring bones for coats and hair, outfit pieces as slots instead of baked into the file, a crowd measurement).</td></tr>
<tr><td>Keep VRoid bases, generate hair and outfits</td><td>VRoid's faces. The garment code from this spike can be refitted to a VRoid body as <code>outfits.py</code> already does.</td><td>The owner still makes four to six bases by hand in VRoid Studio, and every new face needs the GUI again. The anime face under a Cullet coat is a style decision the owner should make by looking at column 3.</td></tr>
<tr><td>Stay with VRoid</td><td>Nothing new to build.</td><td>The cast cannot be made: the two bases are young women (column 3).</td></tr>
</table>

<h2>9. What I could not do, and notes</h2>
<ul>
<li><b>The cached clip library is incomplete.</b> The cache at <code>~/dev/slop-game/.local/kimodo/outputs/library</code> (read only, not copied) has 27 motions; <code>clips.json</code> now lists eight more that are not there (gather, work, eat, play, sit_ground_down, sit_ground, stand_up_ground, dodge). I built only the 13 clips this page needs and generated nothing.</li>
<li><b>No crowd or frame-time measurement,</b> no spring bones, no outfit slots, no level of detail.</li>
<li><b>Cullet's actual 64 residents</b> were not made: their sheets do not exist. The line-up in section 7 is drawn from seeds.</li>
<li><b>The VRoid control</b> is the CC0 sample <code>Sendagaya_Shino</code> fetched by <code>living/tools/lookdev_assets.sh</code>, animated by the unchanged <code>gen_anim.sh</code> steps from the same cache.</li>
<li>The file carries an <code>extensions.VRM</code> block (VRM 0.x is an open format) because that is how the game recognises a character file. It is written as plain JSON by <code>person.py</code>; nothing of VRoid's is in it.</li>
<li>To reproduce: <code>KIMODO_DIR=… living/tools/blender/gen_person.sh</code>, then <code>living/tools/char_spike/capture.sh</code>, <code>media.py</code> and <code>page.py</code>.</li>
</ul>
"""
    doc = f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Scripted characters spike</title>\n<style>{CSS}</style></head>\n<body><main>{body}</main></body></html>\n'
    with open(os.path.join(a.page, "index.html"), "w") as f:
        f.write(doc)
    print(f"wrote {os.path.join(a.page, 'index.html')} ({len(doc) // 1024} KiB)")


if __name__ == "__main__":
    main()
