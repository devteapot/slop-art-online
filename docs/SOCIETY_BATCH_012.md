# Batch 012: assessment repeat and separated readers

Two concurrent four-minute sessions used frozen `m2-2-assessment.1`, fresh Luna-medium controllers and the same fifteen-second cadence without a call cap. [The manifest](../configs/experiments/campaign/012-knowledge-repeat.json) distinguishes the receipt-assessment regression from the initial spatial-separation challenge. This follows [batch 011](SOCIETY_BATCH_011.md), which already demonstrated new archive acquisition after author death.

| Variant | Seconds | Survivors / final health | Calls | Reported tokens | New copies |
| --- | ---: | --- | ---: | ---: | --- |
| Teaching repeat | 240.065 | 2/2: 84, 80 | 16 | 315,229 | One taught personal copy |
| Neighbor readers | 240.116 | 3/4: 0, 100, 100, 100 | 33 | 581,159 | One archive copy; no new reader |

All engine, scope, copy-audit and conservation checks passed. Food accounts reconcile as `24 + 11 produced = 25 final + 10 meals` and `34 + 25 = 42 + 17`. One and two invalid subtree paths, respectively, were rejected without effects. The author death in the second session was an explicit scheduled disturbance; there were no other deaths.

## Assessment and action

In the teaching repeat (`sim-bevy-1788647670510`), Tovan received repeated copies of the same report. Accepted identity event 1911 assessed receipt 1452 (56.204 seconds), although acquisition had already advanced to receipt 1766. The holder retained an explicit interpretation that the report was attributed and unverified. Later receipt 2754 at 108.504 seconds refreshed acquisition without erasing that assessment; final `interpreted_source` remains 1452. This reproduces the previously defective ordering with a real controller.

Tovan chose to verify the report and reached cell 56 at 118.865 seconds (site perception 3048). He found it empty: Mira had already collected all eight units. The learner gained no food there. This is a useful distinction between knowledge influencing a decision and the chosen action yielding a resource. The two characters later incurred ordinary cold exposure outside shelter. Eight teachings created one new personal copy and seven repeat receipts.

## Preserved opportunity without automatic uptake

In neighbor-readers-four (`sim-bevy-1788647671880`), Mira started alone at archive 1; the three readers began at a supplied, sheltered settlement beyond hearing range. They knew the neighboring archive existed but not the report's identity or contents. Mira recorded the report before dying in event 4972 at 120.037 seconds. Six recording operations added one physical copy and repeated it five times.

At completion, archive 1 was the sole accessible in-world copy. No surviving reader had consulted it or acquired the exact report. Travel and a known archive opportunity did not automatically create knowledge. The dead author's retained audit state was not distributed to the survivors. This challenge establishes preservation without guaranteed uptake; the post-death acquisition evidence remains batch 011's actual consultation.

## Final boundary correction

The final milestone source, `m2-3-catalog-bounds.1`, additionally removes archive catalogs from the bounded Rhai **guard input only**. Full catalogs remain in character observations, model context and UI. A deterministic stress test uses 32 local archives containing 32 copies each, with maximum Unicode topic lengths: the full catalog exceeds 64 KiB, yet an ordinary resource guard executes successfully after projection. All 145 Rust tests pass (106 simulation, 31 bridge, five host, one compatibility, two client); this includes 19 knowledge tests. Native authority tools, release WASM and browser assets are built. Nine batch-orchestration tests and the knowledge-summary fixture pass.

No third stochastic run is used to claim verification of this size-boundary correction: its evidence is the targeted maximum-payload execution test and regression suite. The earlier frozen live implementations remain unchanged. The browser client rendered the separated settlements without errors. Stage 2's bounded acceptance combines these checks with batches 011–012 and the explicit limitations in [the evidence record](STAGE_2_EVIDENCE.md).

Retained local evidence is under `output/society-lab/batches/012-knowledge-repeat`, including immutable final captures, model journals, copy timelines, source-linked assessments and completed observer sessions. Frozen `assessment-m2-2` contains 373 hashed artifacts.
