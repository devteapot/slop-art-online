# verify-ui: looks-tex-1-client, KTX2 pictures against PNG

**2026-11-12, branch `looks-tex-1-client`.** It is the client half of [Pictures as KTX2](../../../../../docs/CHARACTERS.md#pictures-as-ktx2): `.thumb.png` summaries for `.ktx2` pictures, `.face.ktx2` before `.face.png`, and the `gpu formats` line with a warning when BC is missing. It was measured on `f26a096d` (based on look-1-client `651e24c2`), then rebased onto main `e6e0c0dc` (look-1 merged), where the code commit is `ec060856`. On the rebased build the client tests passed (122 passed, 1 ignored) and `looks` passed again.

**Bundles:** dev-box's `char-4-composed-643ac265.tar.gz` (PNG) and `char-4-composed-643ac265-ktx2.tar.gz`. The KTX2 bundle was built on dev-box by `pictures.py` (looks-tex-1 `5b080c15`), sha256 `45d3ae7e…ab4f`. All 421 MANIFEST lines check, including 118 `.ktx2`. `looks.json` and `characters/` are byte-identical to the PNG bundle. Each bundle is installed whole as one arm's `lookdev/types`, `styles`, `pages` and strands, switched by links (`.local/looks-tex-1/use_set.sh`, one client binary for both arms). Both arms keep the town's own pages and the PNG `strands.png`, which the local clip file names (docs/CHARACTERS.md, KTX2 pictures in the client).

**The laptop's line** (Apple M4 Pro, Metal): `gpu formats: bc=true astc=true etc2=true (CompressedImageFormats(ASTC_LDR | ASTC_HDR | BC | ETC2))`.

**Cost** (`live_crowd.py`; `.local/looks-tex-1/cost.sh`, `table.py`):

- **Setup:** two Cullet worlds launched fresh back to back at 22:07, one per arm. Uncapped, 30 s still, then the walk.
- **Runs:** three per arm and camera; the order alternates between runs.
- **Medians:** each cell is the median of the three runs, with the range of the three in brackets.
- **Machine load:** the 1-minute load average was 4 to 18 throughout (other workers), so the frame times are noisy.

| | Steady RSS MiB | Peak RSS | Steady footprint | Peak footprint | GPU textures MiB | p50 ms | p99 ms | First view s | Ready s |
|---|---|---|---|---|---|---|---|---|---|
| Play camera, PNG | 939 (928–951) | 947 | 1893 (1869–1967) | 1953 | 357 (350–392) | 4.95 | 15.8 | 2.0 | 2.3 |
| Play camera, KTX2 | 949 (882–958) | 962 | **1802** (1791–1826) | 1868 | **286** (285–292) | 4.66 | 6.3 | 1.9 | 2.2 |
| Full model, PNG | 941 (919–945) | 945 | 1899 (1896–1950) | 1977 | 370 (361–377) | 5.60 | 32.9 | 2.1 | 2.3 |
| Full model, KTX2 | 958 (934–993) | 968 | **1838** (1784–1872) | 1886 | **288** (287–292) | 5.88 | 45.2 | 2.0 | 2.3 |

- **GPU textures** (the client's own count of textures on the GPU) fall by about 71 MiB at the play camera and 82 MiB on the full model, with no overlap between the arms. That is the KTX2 saving on the pictures of the people in view; the whole set, 168 → 56 MiB, shows only when every file is worn.
- **Footprint**, the process's physical footprint including unified GPU memory, falls by about 90 MiB at the play camera and 60 MiB on the full model. The ranges do not overlap at the play camera; on the full model they touch.
- **Resident memory** (RSS) and the IOAccelerator GPU figure move within the run-to-run spread.
- **Frame times and ready time** show no difference beyond the noise. The p99 at this load is dominated by first-sight hitches in either arm. The loading screen's first view comes in at about 2 s in both.

**Checks on the KTX2 arm:**

- `verify-ui-tex1-cullet`, launched fresh, on `f26a096d`: `looks` 14, `names` 4, `windows` 15, **33/33**.
- `verify-ui-tex1-main`, launched fresh, on the rebased `52f0092b`: `looks` **14/14**. No `pictures:` warning appeared, so every `.ktx2` had its summary.

Evidence: `.local/looks-tex-1/cost/` (`table.json`, a `live_crowd.json` for each run), `.local/looks-tex-1/evidence/`, and the run logs under `.local/living/verify/ui-tex1-*/ui/`.

Not covered:
- stills, which dev-box took, in docs/CHARACTERS.md;
- a crowd wearing every file;
- the Spark's `gpu formats` line;
- the browser observer.
