# verify-ui: compose-skirt-scale (spring bones take a scaled bone's scale)

**2026-11-13, branch `compose-skirt-scale` on main `196f8991`.** The only code change is char-4's patch (`~/archive/deliverables/char-4-skirts-client-spring-scale.patch`, byte-identical to the copy in `.local/living/playtest-8/skirts/`). In `characters.rs` `shape`, a `J_Sec_*` child of a bone with its own scale takes that scale (`tf.scale = v`) as well as the scaled offset. Client tests: 128 passed, 1 ignored.

**Assets:** main's today. Bundle `char-4-composed-4ac0eac9-ktx2.tar.gz` (char-4-fringe) from dev-box's archive; sha256 `5ed68697…` matches, every MANIFEST line checks. It is installed in this worktree only: types, styles, pages with the town's own, strands, the book. own-clips was rebaked (`gen_person.sh clips=man`, the library at `.local/kimodo/library`): 84 clips, no pictures. `skeleton_check.py`: 196 files, 0 off. The environments and VRoid bases are links to the main checkout, read only.

**Who the patch reaches:**

- **Composed people:** nobody. Main's style files have `J_Sec_` chains only in hair (90 chains), under `J_Id_Cranium`, which is not scaled in its own frame. No type or style file has one under a body bone.
- **VRoid bases** when a recipe scales them:
  - Shino: 3 skirt chains on each upper leg, the bust on the upper chest.
  - Vivi: 2 skirt chains on each upper leg and 1 on each side of the hips, 2 sleeve chains on each lower arm, the bust on the upper chest.

**Measured** in the asset view, one fixed frame (`idle@0.5`), front and side with plates, and every bone's place (`LIVING_GAME_VIEW_JOINTS`). main's client ran twice (`before`, `before2`), the patched one once (`after`); all three are from this worktree, one asset root. `.local/skirt/shoot.sh` added two measurement recipes for the run only, Shino and Vivi at legs 1.15 and girth 1.2 as char-4 posed Shino, and restored `recipes.json` after. The hem is the skirt chains' `_end` joints (`.local/skirt/hem.py`):

- **share:** its height as a share of the thigh, (upper leg − hem) / (upper leg − knee);
- **width:** its span over the upper legs' span.

| Wearer | Share before → after (scale 1) | Width before → after (scale 1) | Hem above the floor before → after |
|---|---|---|---|
| Shino, scale 1 (`shino`) | 0.3654 → 0.3654 | 2.8153 → 2.8153 | 797.3 → 797.3 mm |
| Shino, legs 1.15 girth 1.2 | 0.3320 → **0.3647** (0.3654) | 2.7363 → **2.8032** (2.8153) | 853.7 → 840.2 mm |
| Shino, legs 1.05 girth 1.05 (`ranger`) | 0.3535 → **0.3654** (0.3654) | 2.7939 → **2.8153** (2.8153) | 830.9 → 826.1 mm |
| Shino, girth 1.3 (`smith`) | 0.3605 → 0.3601 (0.3654) | 2.6899 → **2.7483** (2.8153) | 860.7 → 860.9 mm |
| Vivi, scale 1 (`vivi`) | 0.6473 → 0.6473 | 4.1377 → 4.1377 | 669.8 → 669.8 mm |
| Vivi, legs 1.15 girth 1.2 | 0.5578 → 0.6179 (0.6473) | 3.8886 → **4.1377** (4.1377) | 738.0 → 714.2 mm |
| Vivi, legs 0.66 hips 1.15 girth 1.35 (`small`) | 0.9874 → 0.7435 (0.6473) | 3.6058 → **4.1377** (4.1377) | 175.5 → 199.1 mm |
| Vivi, legs 1.04 girth 0.95 (`runner`) | 0.6217 → 0.6402 (0.6473) | 4.2164 → **4.1377** (4.1377) | 669.1 → 662.4 mm |

- **The flaw:**
  - On main's client a scaled base's skirt keeps the file's size. Shino at 1.15/1.2 wears it 13.5 mm high and narrow.
  - Vivi at legs 0.66 has hers down at the knee (share 0.99) and 13% narrow.
  - Patched, every scaled Shino's hem is at scale 1's place to 0.001 of the thigh.
  - Every Vivi's width is exactly scale 1's.
  - Vivi's place moves most of the way. Her side chains hang from the hips, whose own scale leaves height at 1, as for any body bone.
  - Widths follow girth too: `smith`, girth only.
- **No regression:**
  - At scale 1 both bases are the same in every joint (0.000 mm) and their hem is unchanged.
  - The three composed residents char-4 measured are the same in every joint before, before2 and after (0.000 mm): Amara Okoro `lk_e3e7c990461f9fe3`, Dory Tarn `lk_3124442f979a09b8`, Benedikt Orme `lk_c0314bf12a48f17e`. Main's composed skirts do not change; they have no spring chains for the patch to act on.
  - Their pixel differences are no larger than two runs of main's client differ (springs and timing; `pixels.json`).
- **Sheet:** `.local/skirt/evidence/vroid-skirts.jpg`, Shino and Vivi at scale 1, and at 1.15/1.2 on both clients.

**Scenarios:**

- **`skirt-scale`** (new, `check.py`, 5 checks, no world): **5/5** patched. On main's client **2/5**: Shino's hem place (`ranger` 0.3535 against `shino` 0.3654), Shino's width (2.7939 against 2.8153) and Vivi's width (`small` 3.6058 against `vivi` 4.1377) fail. It covers this from now on.
- **Cullet `verify-ui-skirt-cullet`**, launched fresh from this module, `look_book` `c4-e61b01c0`: `looks` 14 and `far` 11, **25/25**.

**Not covered:** char-4's new skirt files (char-4-skirts `a369a0aba`) on the patched client. dev-box's `~/dev/slop-game` is not on that branch and holds no composed files. The only copies found are in another worker's scratch folder (`char-4-sitting`'s `.local/skirt-new`), whose origin I could not confirm, so they were not used. char-4's own measurement stands for them.

Evidence: `.local/skirt/evidence/` (`hem.json`, `pixels.json`, `joints-*.jsonl`, `scenario-{before,after}.json`, `cullet-looks-far.json`, `vroid-skirts.jpg`), `.local/skirt/shoot.sh`, `.local/skirt/hem.py`; the stills under `.local/skirt/stills/`.
