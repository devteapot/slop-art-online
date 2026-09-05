# Batch 013: first population trials

Four concurrent eight-minute sessions ran the frozen `population-m3-1` implementation (`m3-1-renewal.1`) with [campaign 013](../configs/experiments/campaign/013-population.json). Fresh Luna medium controllers had a fifteen-second post-completion cadence and no call cap. These results establish material fabrication and delayed care, but not the complete Stage 3 evidence gate.

## Observed outcomes

| Variant | Final living / retained population | Creation | Newcomer outcome |
| --- | --- | --- | --- |
| Reproduction | 4 / 4 | None | One person offered; no completed mutual creation |
| Fabrication | 5 / 5 | One artificial person | Alive, health 68, six care meals, one unassessed report, still dependent |
| Scheduled caregiver loss | 3 / 4 | None | Mutual creation attempt interrupted by a parent's scheduled death |
| Capacity pressure | 4 / 4 | None | No additional population to activate the intended five-person shortage |

All sessions reached approximately 480 simulation seconds in 483 wall seconds. Engine, authority scope, food conservation and knowledge-copy checks found no violations. Invalid model proposals and rejected participant operations remain in the records; these checks do not mean every proposal succeeded.

In fabrication, the forty-five-second action was repeatedly interrupted by an eating priority. The character attempted to revise its policy; some patches used invalid paths, and a later full replacement permitted completion. At 229.433s, event 7997 created actor 5 from creator 1's attempt 6588. Event 7996 consumed six actual food. The newcomer had a new identity, zero inventory and no private reports. Its external controller enrolled and made seven actual HTTP-successful model calls, reporting 166,971 total tokens. Two produced invalid JSON proposals; five lacked a top-level call error, but one of those still received a stale-learning-revision rejection. HTTP success, valid output and accepted authority operations are separate facts.

Care arrived after starvation had caused four eight-point health losses between 292.029s and 299.656s. Actor 3 fed the newcomer at 302.021s and 305.980s; actor 4 followed at 310.363s. By the endpoint, actors 3, 4 and 1 had each supplied two meals. The newcomer remained alive with health 68. Actual care therefore occurred, including care by people other than the creator, but it was late.

Actor 3 first taught `camp-provisioning` at 404.523s, event 17271. Twenty-nine teaching deliveries represented one new copy and twenty-eight repeated receipts. The newcomer's final interpretation remained null. It attempted guided practice 91 times without the required personal assessment, then withdrew the unsuccessful practice policy at 476.201s, event 21145. No practice or self-support event occurred. Repeated attempts did not grant mastery or create resources.

The scheduled-loss session did form mutual offers and begin reproduction at 274.630s, event 12372. Actor 1 died at 300.367s. Completion at 304.531s failed because both parents must remain alive, event 13474. No child or creation consumption was committed. This is a live interrupted-creation control; it is not evidence of a newborn surviving caregiver loss.

The pressure session produced no child. Four healthy survivors cannot establish what would happen under the intended higher population demand. Creation remained a choice rather than an automatic response to the scenario motive.

## Material accounts

All quantities are actual retained food units, including carried and site stocks. Consumption through care and creation is separate from ordinary eating.

| Variant | Initial + produced | Final + eaten + lifecycle costs |
| --- | --- | --- |
| Reproduction | 24 + 43 | 26 + 41 + 0 |
| Fabrication | 28 + 53 | 28 + 41 + 12 |
| Scheduled loss | 24 + 42 | 28 + 38 + 0 |
| Capacity pressure | 24 + 46 | 29 + 41 + 0 |

Fabrication's twelve lifecycle units are six construction nutrients and six care meals. Nominal source capacity is not measured production: stock ceilings suppressed some growth opportunities. Repeated teaching consumed energy but did not duplicate food or produce new distinct knowledge copies.

## Defects and next experiment

A care proposal at 376.511s was rejected as `target not perceived` although the actor's own local lifecycle observation listed the newcomer. Policy target validation checked only short-lived `memory.from` entries. The fix accepts target IDs from the same actor's retained lifecycle site observations as well; it never resolves a guessed ID against the world roster. Tests cover successful install and patch after arrival-memory eviction, and rejection after removing the owned observation even while the child remains physically nearby.

Repeated malformed patch paths such as `/2` and `/root/0` motivated clearer canonical `root/2` examples. The parser still rejects malformed paths rather than guessing the intended subtree.

Controller recovery could indefinitely replace planned communication and learning slots with behavior retries. The newcomer received its report late and did not complete assessment afterward. The next implementation preserves the scheduled responsibility and supplies failure feedback without taking over another role's slot. This is a scheduling fix, not automatic learning or repaired model output.

[Campaign 014](../configs/experiments/campaign/014-population-repeat.json) uses fresh twelve-minute reproduction and fabrication repeats, a parental-reserve comparison, and a matched fabrication trial with scheduled actor 3 loss. That actor was an actual caregiver here; it must establish that relationship again in the new run before the intervention can count as caregiver loss. No costs are shortened, care tree installed or report assessment granted.

## Retained artifacts

Local evidence lives under `output/society-lab/batches/013-population/`, with `POPULATION_RESULT.json`, `KNOWLEDGE_RESULT.json`, `SOCIETY_RESULT.json`, `LIVE_RESULT.json`, model journals and complete final authority snapshots per variant. The frozen implementation manifest retains source and binary hashes. Final snapshot SHA-256 values:

| Variant | SHA-256 |
| --- | --- |
| Reproduction | `a1ec43ff8da073f63caf0712276e7a59864bf4cc970c4d4f6e58dae135e8f745` |
| Fabrication | `5702c053da801ba3b47d8e2e8428b0d27b2bbf0b9922fa49b905cce0393d9610` |
| Scheduled loss | `f9bc237843cb7992125252f2c468369f6f7f394f28ca98961403ddf599a2c048` |
| Capacity pressure | `967cd07095d7e277280702b3b3ceb95b51770a16e4484a0ebb5a4b1cbdd87450` |
