# Mixed remains and a tablet, 2026-11-18

`core-seen-mixed-1118-212959` passed 6/6 checks against the release authority at `fb14e695`. A character learned writing and wrote a real tablet. Admin staged its death alongside two other people and three deer before the observer arrived. The tablet moved to the author's remains. On arrival the observer received exactly two lines, including the author's individual line and this grouped line.

> You notice the remains of 2 strangers and 3 deer around you, the nearest 2 tiles east.

The first attempt, `core-seen-mixed-1118-212921`, used the wrong structure-holder tag in the test assertion. The corrected attempt used `STRUCTURE_BIT` from `tables.rs`. The product code stayed at `fb14e695`.

The fixture, snapshots, actions and results are under `.local/living/seen-ranges/mixed-remains.py` and `.local/living/verify/core-seen-mixed-1118-212959/`. The scratch database was paused and archived before removal. The scene exercised a tablet. It did not stage a sign or time the bystander wake.
