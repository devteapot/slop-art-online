# Random Middle acceptance sample for c4-d357edaf

The household split passes. The native-pixel sample fails. Of 887 lines, 201 wear coats. The dark / light counts are 86 / 115 (42.8% / 57.2%). Named residents across age bands contribute 17 / 28, the pool 62 / 75 and decor 7 / 12. Among current named residents the split is 8 / 12. The 16 named households represented among coat lines split evenly by variant. Their different numbers of coat-wearing lines account for the resident-line skew.

The histogram of exported sRGB coat colours, counting each line once, is orange/brown 66, blue 43, low saturation 40, yellow 19, purple 12, red 11 and cyan 10. This uses HSV hue with sector boundaries at 15, 45, 75, 165, 195, 255, 315 and 345 degrees, and assigns saturation below 0.15 to the low-saturation group.

The sample uses Python's `random.Random(20261119).sample(sorted(coat_line_keys), 30)` without replacement. It drew 16 light and 14 dark. Each PNG contains the native meadow crop, garment ID pass and ground-change pass in the order expected by [the four-body checker](../check.py). The release client rendered the fixed Middle stop at 15:00, 1280 × 720, idle at one second, yaw 20°. All 30 lines had enough pixels to measure both garments.

| Metric | Mean | Minimum | Gate |
|---|---:|---:|---:|
| Coat / jersey | 3.064 | 2.176 | 2.5 |
| Figure / grass | 2.035 | 1.337 | 1.5 |

All 14 dark coats and one light coat pass. The table lists every failing light coat. [Full measurements for all 30 lines](sample.csv)

| Key and native crop | Coat / jersey | Figure / grass |
|---|---:|---:|
| [lk_9ae288fbafd00734](lk_9ae288fbafd00734.png) | 2.447 | 1.485 |
| [lk_bf73bcc284c8ec57](lk_bf73bcc284c8ec57.png) | 2.284 | 1.428 |
| [lk_4bf0c9d9cb8a909f](lk_4bf0c9d9cb8a909f.png) | 2.217 | 1.403 |
| [lk_043a62fb5a4ec150](lk_043a62fb5a4ec150.png) | 2.441 | 1.433 |
| [lk_5c300adbfb5307d5](lk_5c300adbfb5307d5.png) | 2.417 | 1.406 |
| [lk_b39307ba40c28713](lk_b39307ba40c28713.png) | 2.213 | 1.565 |
| [lk_d74fb5052eca6685](lk_d74fb5052eca6685.png) | 2.442 | 1.337 |
| [lk_144dc6722b205268](lk_144dc6722b205268.png) | 2.310 | 1.338 |
| [lk_64bebc1f9e0a1a40](lk_64bebc1f9e0a1a40.png) | 2.212 | 1.600 |
| [lk_12d800c3d0633037](lk_12d800c3d0633037.png) | 2.176 | 1.534 |
| [lk_086b97002477946c](lk_086b97002477946c.png) | 2.384 | 1.448 |
| [lk_9b2bdd5295789beb](lk_9b2bdd5295789beb.png) | 2.583 | 1.432 |
| [lk_a3655149c6415274](lk_a3655149c6415274.png) | 2.395 | 1.391 |
| [lk_73b1a8e027679aab](lk_73b1a8e027679aab.png) | 2.186 | 1.524 |
| [lk_f003790ed0519076](lk_f003790ed0519076.png) | 2.255 | 1.419 |
