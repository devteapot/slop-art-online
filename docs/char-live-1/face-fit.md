# Cora face fitting checkpoint

Pass 2 is open after two high-effort fits. The first fit established the asymmetric fringe, facial silhouette, painted features and three interwoven strands at the centre back. Its three-quarter view exposed a smooth cap on the visible side and a missing ear. The second fit added a swept side volume, tucked lock, ear relief and a more prominent nose. At turnaround scale the braid reads down the back. At portrait scale a gap and fragments of pale sheet background appear at the crown, the near ear is obscured by crossing locks, and the jaw-to-neck junction is abrupt. The painted features also need expression-ready eye and mouth separation. The second portrait remains below the approved sheet.

| Attempt | Three-quarter close-up and overlay | Four-view orbit and overlays |
|---|---|---|
| First fit | [Portrait](p2a-portrait-review.png) | [Orbit](p2a-review.png) |
| Second fit | [Portrait](p2b-portrait-review.png) | [Orbit](p2b-review.png) |

**Next fitting attempt at xhigh.** Keep the head landmarks and rear plait anchor. Rebuild the crown and sweep as adjoining surfaces that share a continuous root. Give the ear its own clear opening in profile and three-quarter. Repaint the lock atlas with edge dilation so no background or neighbouring feature is sampled. Match the cheek silhouette and the plane under the jaw before accepting the pass. Clothing and the later passes await this portrait decision.

## Files and replay

The live scene checkpoint is [cora-face-progress.blend](cora-face-progress.blend). Both source drawings are packed. The replay requires the adjacent face and turnaround sheets. Use this command in the session directory after the host gate clears.

```bash
OCIO="$PWD/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/rebuilt" "$HOME/.local/share/slop-tools/build-bin/blender" -b --factory-startup -t 2 --python-exit-code 1 -P replay.py
```

The live bridge was restarted between fittings to use [standard.ocio](standard.ocio). The restart restored the ordered journal into the bridge namespace, and the journal contains both fits. OCIO 2.4.2 validated the config and converted 18% linear gray to 0.46135 sRGB. Blender reported loading the supplied config. The second fit uses the Standard view with flat Workbench light for texture and silhouette inspection. [Sheet value samples](value-targets.json) provide targets for the later shading pass. Game values have yet to be measured.

The separate [four-body proof plan](four-body-proof.md) describes the proposed masters, deformation controls and likely fit failures on each generator body. Its first experiment would fit the crown and plait. No generator code was changed.

Replay from factory startup regenerated the second portrait and four orbit PNGs. The portrait, front, profile and back matched exactly. The 320 × 810 three-quarter image differed at one pixel (199,64), by one 8-bit level in red and green. Session time for this stage was about twelve minutes including the wait for the performance gate. No images were generated through an external service and no game build was started during pass 2.
