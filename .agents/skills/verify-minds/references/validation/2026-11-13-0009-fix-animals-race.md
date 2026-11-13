# verify-minds: fix-animals-race

## 2026-11-13 fix-animals-race on main `8420a4e7` (Spark, scratch server `slop-move-stdb` 127.0.0.1:3361, fake model)

The `animals` case was on the red-on-main list as flaky (main 2 of 3). Its staging now sets up its own herd (features/animals.md, "Staging"): three adults with nothing pending, every other deer held and moved off, the three fed by two grazings, the person 4 m from the lead again before its throttle ends, calls counted per deer by its prompt's `you.id`. Merged onto main's own-decision version of the case (pack retired): each of the three makes its own call, and the lead asked again makes none.

- Main (`fix-animals-race`, `8420a4e7`): `minds-an6-main-1` … `-5`: 5 passes in a row (later calls 0 for each deer).
- `pursue-last-seen` (`9e2b25a5`) with this driver: `minds-an6-branch-1` … `-5`: 5 passes in a row.
- Earlier attempts and the races they found: `minds-an3-*`, `minds-an5-*` (the lead's own re-think at +246 s; a lead crossing hunger 50), the reverted first attempt (`minds-an3-main-180351`: the three had requests pending from their own instincts, so each chose for itself).
