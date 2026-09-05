# Batch 015: connected settlements

Four fresh eight-minute sessions used [campaign 015](../configs/experiments/campaign/015-multisociety.json), frozen as `multisociety-m4-1`, with the existing `m3-2-perceived-care.1` gameplay authority. Six people began in pairs at western cell 82, eastern cell 93 and southern cell 152; the scale sample doubled population and physical stocks/source amounts. All settlements shared one arena. Population renewal was disabled and every initial identity remained in the final records, including deaths.

## Outcomes

| Variant | Simulation seconds | Final living / retained | Recorded outcome |
| --- | ---: | --- | --- |
| Baseline | 480.252 | 5 / 6 | No inter-camp arrival; actor 4 died at eastern camp 93 |
| Pressure | 480.178 | 5 / 6 | Actor 4 used western food; actor 3 died in the east |
| Scale | 479.709 | 11 / 12 | No inter-camp arrival; actor 3 died and actor 4 finished at health 4 |
| Disputed | 480.311 | 5 / 6 | Three people visited other camps; actor 6 died in the south |

The deaths were starvation deaths: baseline actor 4 at 350.331s, event 21930; pressure actor 3 at 217.757s, event 17079; scale actor 3 at 443.334s, event 27473; disputed actor 6 at 217.620s, event 15401. Pressure actor 4 also accumulated nine weather hits while moving, finishing health 82. Disputed actors 3 and 5 finished health 54 and 48 after weather/starvation damage. Local deprivation remained possible while food existed elsewhere.

All final fixed-identity, movement/residence, food-conservation, knowledge-copy, authority-scope and engine checks passed. The scale sample stopped slightly before 480 simulation seconds at its wall-time limit. These checks do not imply successful proposals, survival or cooperation.

## Travel, residence and material use

| Variant / actor | Initial home → visited camp | First arrival | Total time at nonhome camp | Completed gathering / eating there |
| --- | --- | --- | ---: | --- |
| Pressure / 4 | 93 → 82 | 40.873s, event 2487 | 369.627s | 10 / 7 |
| Disputed / 3 | 93 → 82 | 124.815s, event 8656 | 198.752s | 8 / 4 |
| Disputed / 4 | 93 → 152 | 33.229s, event 2073 | 447.082s | 16 / 10 |
| Disputed / 5 | 152 → 82 | 299.054s, event 19225 | 181.257s | 16 / 4 |

These are committed journeys and real food collection, not teleported replacement inhabitants. Initial-home labels describe origins, not continuing ownership or allegiance. Pressure actor 4 and disputed actors 4 and 5 finished at the visited camps; disputed actor 3 returned to cell 93. The observations establish residence and resource use away from initial homes, not a migration agreement or permanent membership.

Pressure actor 4's command 2265 at 38.349s proposed checking western supplies and returning home. Conflicting home/away priorities instead caused 212 western arrivals, mostly short departures and returns around the camp. The final uninterrupted western stay began at 228.618s. Disputed actor 3's decision 27189 at 424.084s proposed a supply loop after 45 failed gathering attempts; its opposing movement priorities similarly caused repeated departures and returns around the eastern camp. A reported transport intention was not a completed delivery.

No direct food transfer between initial-origin groups and no site deposit occurred in any variant. Travelers consumed or retained food they collected; the results do not establish gifts, reciprocal trade, a maintained supply route or delivered aid. Food is fungible, and these records do not justify assigning particular carried units to a promised shipment.

## Information that did and did not travel

In baseline, actor 5 taught `western-provisioning` to colocated southern actor 6 at 26.676s, event 1589. Ten deliveries were one new copy and nine repeats. Both actors began at cell 152; this was not cross-origin record distribution. The recipient never personally interpreted the exact received report. No other variant taught an exact useful report. Disputed actor 5 recorded `western-provisioning` in the southern archive at 33.107s, event 2057, followed by sixteen repeat writes; nobody consulted it.

There was, however, personally interpreted information exchanged between people from different camps in disputed:

- At 342.661s, Iri 3 reported eastern food insecurity and requested voluntary transport. Western Mira 1 received speech perception 21784, then produced her own attributed assertion 24229 at 378.828s. Her interpretation explicitly distinguished Iri's report from verified current eastern stock.
- At 350.027s, Mira offered to carry or deposit surplus after confirmation. Iri received perception 22282 and produced his own assertion 24003 at 375.147s. He treated it as a promise requiring verification, not an actual transfer.

These are source-linked subjective interpretations of communication. They are not exact-record copies, shared agreement or delivered assistance. Later Iri chose the unsuccessful supply loop described above; the reporting tool found no material action with an explicit report-ID reference or report-citing guard. Chronology alone cannot establish that the new assertions caused that policy.

The disputed seed gave actor 4 a distinct, mistaken `western-provisioning-denial` report while actor 5 held the positive report. Actor 4's decision 1838 at 30.411s chose to investigate the south because the eastern site had no observed food; it did not explicitly cite the denial. Actor 5's decision 19038 at 294.888s described western provisioning as plausible and sought a fresh observation after southern failures. The contrasting trips are evidence of choices under different private reports, not a controlled causal estimate of the mistaken report's effect. No automatic reconciliation, teaching or belief copying occurred.

## Actual food and model accounts

| Variant | Initial + produced = final + eaten | Source production at 82 / 93 / 152 | Model journals | Reported tokens |
| --- | --- | --- | ---: | ---: |
| Baseline | 22 + 68 = 34 + 56 | 28 / 16 / 24 | 107 | 2,306,566 |
| Pressure | 22 + 70 = 39 + 53 | 46 / 0 / 24 | 97 | 2,088,568 |
| Scale | 44 + 132 = 59 + 117 | 56 / 30 / 46 | 193 | 4,232,797 |
| Disputed | 22 + 65 = 34 + 53 | 41 / 0 / 24 | 94 | 2,017,675 |

Nominal baseline source rates were 6/2/3 food per minute. Pressure and disputed removed the eastern source; scale doubled source amounts and stock ceilings. Actual output differs from those ceilings: baseline western stock frequently filled, while pressure's traveling collector left room for more production. In disputed, new western demand exhausted its stock even as southern stock later recovered. Global production greater than a reference metabolism budget did not guarantee food was available to the person who needed it.

All 491 call journals, including incomplete/cancelled calls and malformed outputs, remain retained. Authority rejections included stale revisions, invalid reflection sources/trust targets, invalid policy structure and shutdown races. Reported token usage is not an assertion of effective provider reasoning effort. Each participant continued to use only its own scoped context.

## Reporter correction and retained evidence

Live damage exposed a postprocessing defect: the residence analyzer read `after.position` on nonmovement events, but damage uses an integer `after` health. Position extraction now runs only for actual movement. Eight recorded-evidence tests pass, including integer damage before and after a journey. The frozen authority and its snapshots were not changed; the corrected working-tree reporter processed them after completion.

Each variant under `output/society-lab/batches/015-multisociety/` retains `MULTISOCIETY_RESULT.json`, `KNOWLEDGE_RESULT.json`, `SOCIETY_RESULT.json`, `LIVE_RESULT.json`, model journals and a final authority snapshot. Final snapshot SHA-256 values:

| Variant | SHA-256 |
| --- | --- |
| Baseline | `9f4904e3d74fcd8bec5d66f01430cd08848e682b5215b7a4669b17103498ccc9` |
| Pressure | `bafc3b7d451cd43086ea81bad2ddb770a210d4166a4ac744043602402a45ccad` |
| Scale | `a764e5de61e8a5cf78e61d4bd52e98bdca1cd04adff9f7d856d35cf11e96f832` |
| Disputed | `3dced1486b590790626a675cbde4d96e682c938984092296f9304d71782f3a40` |

The bounded result is connected settlements with physical movement, unequal resource access, residence away from home, source-linked communication and interpretable failures. Sustainable communities, successful aid, reciprocal trade, exact useful-report transmission between origin groups, information-caused migration and stable shared institutions remain unproved.
