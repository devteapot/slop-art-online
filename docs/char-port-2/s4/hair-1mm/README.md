# The hair page's 1 mm a texel: a lock-line prototype

The GC asked for one lock-line close-up at the hair-mask page's density, 1 mm a texel (HANDMADE_COMPOSED.md, "The hair-mask page"), before S5 commits to it.

**Verdict: 1 mm holds.** Cora's lock lines don't break up at portrait or close-up. They come out slightly fainter where a line passes between texel centres. At Near nothing changes. No finer hair page is needed.

**The prototype:** Cora's accepted file (`docs/char-live-3/ink-batch-2/own-cora-live.glb`, v1.1 lock ink, `ink_px` 1.05, fade 2.0) drawn twice with the same client:
- **as accepted:** her 2048² `.hair.png`, about 0.30 mm a texel at the hair's median density (0.62 m per UV unit; the 10th to 90th percentiles span 0.2–3.2 m);
- **at 1 mm a texel:** the same mask at 618² (2048 × 0.302 / 1.0).
  - **G (the lock lines' distance):** point-sampled at the coarse texel centres, which is what a field made at that density holds.
  - **R (the highlight):** box-averaged.

| Shot | Pixels lighter at 1 mm (> 8 levels) | Darker |
|---|---|---|
| Front portrait | 245 | 62 |
| Three-quarter portrait | 299 | 38 |
| Back portrait | 99 | 5 |
| Front close-up (zoom 0.18) | 318 | 159 |
| Near, front and back | 0 | 0 |

[Portraits: as accepted on the left, 1 mm on the right](portraits.png) · [Three-quarter, 4× nearest](three-quarter-zoom.png) · [Close-up, 4× nearest](close-zoom.png) · [Shots script](shots.py)

**Why it holds:** these lock lines are `"px"` lines (HANDMADE_INK). Their width is set in screen pixels from the distance field, and a bilinear distance field 3.3× coarser still places a centreline within a fraction of a pixel at these views. What is lost is a little weight where two centrelines lie within about 2 texels of each other, or where a centreline bends sharply between texel centres.

**For S5:** author the page at 1 mm, keeping the contract's island and line padding. One caveat: Cora's hair map wasn't uniform (some islands were already coarser than 1 mm), so S5's packed lock islands at a uniform 1 mm are no coarser than parts of her accepted hair.
