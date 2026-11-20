# Cora’s stage 4 hair review

**GC verdict: pass, with a recorded defect.** The swept front and three-quarter locks and silhouette match the drawings. In profile and back, the evenly spaced parallel lines read as stripes. The nape hides the start of the braid. The 58° play camera favours the crown and back. A separate pass immediately after this session will group the locks into a visible braid start and vary line spacing and weight.

The accepted file uses fade 2.0. Ink defines close-ups. At play distance the bands and silhouette carry the lock definition. The GC accepted the floor-relative target of (65,41,33). The tables and original reports below preserve the submitted comparison at commit `1a5504bff`. [Accepted calibration](accepted-calibration.json)

The fixed daylight portraits show 10 distinct front tips and 8 at three-quarter, including the hanging jaw locks. From behind, the side locks gather at the nape and the three plait strands cross in shadow. The four auburn swatches pass in both calibrated portraits. The absolute ink swatch misses in green and blue. The measured black floor and a proposed display-relative target are below. [Drawing and game pairs](review.jpg) · [Numbered lock tips](lock-counts.jpg) · [Braid in shadow](braid.jpg)

| Measure | Drawing target | Game asset |
|---|---:|---:|
| Outer spread / cheek width | 1.87 ± 0.10 | 1.870 |
| Crown lift / head height | 0.096 ± 0.035 | 0.124 |
| Rear depth / head height | 0.53 ± 0.04 | 0.530 |
| Front tips | 10 ± 2 | 10 |
| Three-quarter tips | 9 ± 2 | 8 |

The profile and crown use continuous normals within each lock and separate normals at lock boundaries. The shadowed braid crop enlarges the actual rear frame. The two play-camera pairs use the overhead drawing, the closest angle available on the turnaround. [Rest-pose measurements](volume.json) · [Full-resolution rear frame](stills/07-clip-idle@0-180_8_0.75_0.68.png)

## Daylight colour on the dev-box AMD GPU

| Swatch | Drawing target, sRGB | Base, sRGB | Front | 45° |
|---|---|---|---|---|
| Shade | 88, 42, 27 | 43, 4, 1 | 89, 49, 35 | 81, 36, 25 |
| Mid | 152, 72, 43 | 104, 37, 8 | 145, 69, 43 | 145, 65, 37 |
| Light | 171, 88, 56 | 119, 43, 6 | 171, 88, 60 | 171, 87, 59 |
| Highlight | 187, 99, 63 | 135, 47, 3 | 185, 96, 68 | 185, 93, 65 |
| Ink | 59, 27, 18 | 4, 0, 0 | 65, 39, 33 | — |

The contract audit recorded zero errors and zero warnings. The colour check recorded eight of nine patches within ±8. The initial frontal light window at (821,266) overlapped an authored ink line. The registered centre (826,271) keeps the 9 × 9 window inside the same light band. In the plain control the corresponding windows differ by at most one level per channel. Ink uses its original coordinates throughout. [Production targets](own-cora-live.calibration.json) · [Calibration report](calibration-report.json) · [Per-channel deltas](colours.csv)

The independent fade 2.0 calibration returned 8 of nine patches within the original tolerance and a clean contract audit. Its registered ink measured **(65,39,33)**. Across fade settings 9 of nine measurements were identical. [Fade 2.0 calibration frames and report](fade2-calibration/report.json)

### Ink contrast and the black floor

The 1600 × 900 portrait uses an 11:00 sun, the default grade and idle at 0 seconds. Coordinates start at the upper-left. The registered ink window spans x = 749–753, y = 293–297, centred at (751,295). Min5 picks a single RGB pixel with the lowest display luma in that window. With all five hair swatches set to black and a 1.6 px control line, the minimum is **(34,32,29)** at (749,293). The original target’s blue acceptance interval ends at 26. At the production width of 1.05 px, a separate control that set only the ink dye to black on the auburn hair yielded (63,39,33). The second ink frame with base (12,0,0) yielded (69,39,32). [All-black frame](black-floor-portrait.png) · [Registered windows and magnification](ink-floor-comparison.png) · [Second ink frame](ink-second-portrait.png) · [Trial measurements](ink-trials.json)

Production ink is **(65,39,33)**, or **(+31,+7,+4)** above the black floor and **(−80,−30,−10)** below the rendered auburn mid. The mid is the 9 × 9 channel median at (759,341) in the same frame. The original ink delta is (+6,+12,+15). In linear luminance the ink sits 13.6% of the way from the floor to the mid. The drawing’s ink luminance is 15.3% of its mid.

**The GC accepted (65,41,33) as the dev-box ink target.** Decode the measured floor and mid with the sRGB transfer function. For each linear channel, divide drawing ink (59,27,18) by drawing mid (152,72,43), also decoded. Multiply this ratio by the rendered mid minus floor, add the floor, then sRGB-encode and round once. The production result differs from this target by **(0,−2,0)**. Both calibration files retain the original drawing sample alongside the accepted target. A GPU confirmation can repeat the same registered measurements and report its own floor. [Contrast calculation and source values](ink-contrast.json)

## Middle motion and fade choice

The still compares hair with its ink fields removed, then file overrides 2.0 and 3.0. It shows a native-pixel crop and a 4× nearest-neighbour enlargement. The two full-resolution clips use the same embedded walk, 150 sampled poses and 150 camera angles. The viewer normally applies a gait path from the shared clip library to an asset whose name starts with `own-`. That introduced a background offset in the first comparison. The delivered captures both use the embedded clip path, which removes that discrepancy. Cora takes five one-second walk cycles as the camera turns from 20° to 34.9° at 0.1° per frame. Both use the Middle camera at 12 m, looking down 58° with a 44° field of view. The encodes are lossless RGB VP9, 1600 × 900, 30 fps, five seconds. [Middle comparison](middle-comparison.png) · [Walk at fade 2.0](middle-walk-2.webm) · [Walk at fade 3.0](middle-walk-3.webm)

The official tool compares 16 stills per sequence against the same file with the ink fields removed. It divides the ink’s normalized second temporal difference by the hair edges’ normalized second temporal difference. A ratio at or below 1.5 passes. Below one ink pixel per frame darkened by more than eight display levels, the tool reports “faded” and omits the ratio. [Fade 2.0 measurements](shimmer-2.json) · [Fade 3.0 measurements](shimmer-3.json)

| Stop and motion | Fade 2.0 ink px/frame | F ink / F edge | Ratio | Fade 3.0 ink px/frame | F ink / F edge | Ratio |
|---|---:|---|---|---:|---|---|
| Near pan | 0.0 | faded | — | 0.0 | faded | — |
| Near zoom | 0.0 | faded | — | 0.0 | faded | — |
| Middle pan | 0.0 | faded | — | 0.0 | faded | — |
| Middle zoom | 0.0 | faded | — | 0.0 | faded | — |
| Far pan | 0.0 | faded | — | 0.0 | faded | — |
| Far zoom | 0.0 | faded | — | 0.0 | faded | — |

Both tool runs returned success with all six sequences faded. The shader estimates line spacing from the median metres per UV unit of the hair primitive. Measured on this unwrap, that is 0.69089 m per UV unit. With the authored field range of 0.009 UV the spacing estimate is 12.44 mm, about 1.54 pixels at the shader’s reference Near pixel size. Both candidate fade thresholds exceed that estimate. The numbered portrait tips describe close-up readability. The play-distance sequences give the GC evidence of how early the lines disappear.

Across all 150 walking frames the two independently rendered arms matched pixel for pixel. The same was true for each arm against the plain reference over all 96 idle pan and zoom frames. Three frames per encoded clip (0, 74 and 149) decoded exactly to the original RGB pixels. The clips therefore show the same Middle result at both settings. The GC selected 2.0 for the production file. [Frame and encode checks](motion-check.json)

## Asset and replay

The standalone GLB contains **48,896 triangles**, six clips and 15 face expression keys. Independent factory startup reproduced its SHA-256 `413badd00ec57b2910bcef088aebcc92c37a48ed46d8c70c454a0735b7ab15a1`, both sidecars, the authored line guide and its UV layout. The six Blender orbit and play-camera images match pixel for pixel. The GLB’s seven face primitives retain the approved stage 2 morph payloads. Replaying the expression sweep changed the face for every key and returned exactly to neutral. [Editable scene](cora-final.blend) · [Accepted GLB](own-cora-live.glb) · [GLB at fade 2.0](own-cora-live-fade2.glb) · [Factory replay check](replay-check.json)

The authored 2048² sidecar carries the highlight in R and the line distance in G. B is zero. The line guide has 11,908 zero-distance texels. The topology check covers all 24,276 hair triangles on the exact exported UV0. Every triangle lies within one of the 32 registered islands, including the scalp support at its wrap. The material audit found the three generated maps in Blender. [Line guide](lock-lines.png) · [Packed R and G](own-cora-live.hair.png) · [UV audit](seam-audit.json) · [Material audit](material-audit.json)

To rebuild, run the journal from the repository root with the session’s Blender shim. Set `CHAR_LIVE_OUTPUT` to an empty output directory. The original review used fade 3.0. The final journal entry applies the GC’s fade of 2.0. The original comparison changed only `ink_fade_px`. Both GLB names now resolve to the selected 2.0 asset. [Session journal](../../session.jsonl) · [Replay entry point](../../replay.py)

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
CHAR_LIVE_OUTPUT="$PWD/.local/cora-stage4-replay" "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-2/replay.py
```

For the generator back-port, keep the lock’s surface normals continuous between sections and keep independent normals where locks meet. Generate the face-framing tips, rear gathering curves and three interwoven braid strands in scalp coordinates. Output each lock’s UV island and its authored R highlight alongside the one-texel line guide, run the existing distance-field writer into G, and emit the palette and matching ink range. Preserve the approved jaw and chin rows and the rest-pose forward face UVs when fitting the hair opening to another head. [Cage fitting and expression evidence](../../resumed-profile/README.md)

## Time and usage

Stage 4 ran from approximately 17:23 to 20:54 UTC on 19 November 2026, 3 h 31 min elapsed including coordinator holds. There were two high modelling attempts and one xhigh attempt. The final comparisons used one release client built on the dev-box, one independent factory replay, two official shimmer runs sharing a 96-frame plain control (288 game stills total), and two delivered 150-frame walks. One extra walk capture exposed the gait-path mismatch. The private Cargo target was removed after the release build. Token totals were unavailable. Living-check is deferred to the merge gate.
