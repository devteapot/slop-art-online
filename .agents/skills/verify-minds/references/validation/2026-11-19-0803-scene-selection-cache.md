# Scene selection cache, 2026-11-19

The pinned private SpacetimeDB 2.14.1 fixture timed the complete scene function over one paused state with 2,700 remains. It rotated C2, uncached bounded R1/R2, forced misses and repeated hits in 20 batches of 96 calls per arm. Median costs were 532.06, 491.13, 496.72 and 320.01 µs/call. The setup and raw timing evidence are under `.local/living/seen-ranges/scene-fixture/`. A same-transaction mutation probe checked repeated equality, exact counts on addition and deletion, and regrouping on adding and removing a tablet.

- `minds-cached-scene-1119-080155` passed 6/6. The captured prompt still contained one count of 18 strangers, two named bodies, one readable body and six shelters.
- `core-seen-cache-1119-080251` passed 15/15. The core field still had exact notices, no retelling on return, successful legacy migration and death cleanup.
- `just living-check` passed. The authority and seed-law check ran, and unchanged steps reused their stamps.

The first integration attempts timed out while publishing two ticking worlds on the single-core fixture server. The retry used four cores and sequential launches. A later attempt exposed a writer killed during random setup. The case now moves the writer to the clear test line before waiting for its tablet. The failed trials and retry results are retained with the other evidence.

The timed fixture remained paused. The integration worlds used the private server on port 3388 and the local fake provider. The interleaved battle replay is pending the coordinator's all-clear. See [the deterministic timing and cache design](../../../../../docs/SEEN_REMAINS.md#same-state-scene-timing-and-selection-cache).
