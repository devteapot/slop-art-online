# Batch 004: entry conditions and controller recovery

Matched supplied clearings ran eight minutes. The unchanged social version finished with one survivor (Iri, 70 health); recovery finished with three (Mira 42, Tovan 100, Renn 100). Calls were 48 vs 63, reported tokens 767,234 vs 1,090,200. No detected scope errors, engine errors or food-conservation violations occurred. This is a promising implementation result, not a statistical ranking from one sample.

The recovery characters used the new `when` nodes. Mira contributed eight shelter units and Iri four. Food moved into camp, and all three survivors consumed 10–12 meals, beyond their individual initial stocks. However, raw activity counts greatly exaggerate useful work: Tovan gathered 189 units and deposited 177; Renn gathered 116 and deposited 96. Much of this was withdrawing and redepositing the same shared food. Net flow, not action totals, must be used to judge provisioning.

Iri still died at the thicket. Her last plan began with a camp-only condition despite being outside camp, and a waiting fallback masked the failed sequence. Failures and cold damage then occurred while the fixed communication/learning rotation postponed another behavior call. The baseline also had five stale-learning rejections while characters were taking damage. These remain real limitations.

Next: preserve the promising recovery build and run a fresh repeat alongside a version with an actor-private 60-second activity summary and earlier behavior reconsideration after new failures/harm. The summary records withdrawals, deposits, net local food changes, movement, stationary move completions and action outcomes. It neither sees other minds nor supplies a policy. Learning revision semantics remain unchanged in this comparison.

Final evidence is captured synchronously in each run's `final-snapshot.json`; `SOCIETY_RESULT.json` records conservation, individual outcomes and speech-linked learning. Public deposits alone are insufficient for a society pass; trace who relocates resources and who benefits.
