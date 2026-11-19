# verify-core: battle-diagnosis

Branch `battle-diagnosis` (from main `b36a938c`), the trial service `slop-trials-stdb`, default seed, `scoped`, private `CARGO_TARGET_DIR`.

- **Change:** diagnostics only. They are counted and logged only while profiling (`common::diag`, `report_diag`); spans on `brain.noticed`, `brain.graph`, `brain.after`, `perceive.scene_json`.
- **Results** (`core-bd-125522`): `tick` 6/6, `sight` 6/6.
- **`just living-check`:** exit 0.
- **Measurements:** docs/BATTLE_SCALE.md (`living/tools/battle_diag.py`; runs `minds-bdnm-122050`, `minds-bdat-124436`, `minds-bd200-123543`, `minds-bd100d-120959`).
- **Not covered:** the rest of the baseline. No behaviour changed.
