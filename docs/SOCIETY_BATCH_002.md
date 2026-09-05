# Batch 002: evidence retention, rejected implementation

The successful launch is `output/society-lab/batches/002c-evidence`. Two earlier attempts failed before the shared start: millisecond database-name collision, then an occupied port left by the first attempt. Initialization is now sequential and clocks still release together; future host database names also include process IDs. Failed launch records are retained.

Over 300 seconds, both implementations had 9/12 survivors. Contract-only: 112 journaled calls, 2423 updates, 16 accepted learning operations, 11 lost-source learning rejections. Evidence candidate: 99 journaled calls, 1835 updates, 22 accepted learning operations, no lost-source learning rejections, but **23 rejected attempts to retain a read**. Reads were observed through a live subscription, and the oldest events could disappear before the subsequent retain command arrived. This candidate is not accepted as the final evidence contract.

Provider availability also deteriorated: contract-only journals contain 12 HTTP 502 failures, 13 response-body failures and 2 transport failures; evidence journals contain 10 HTTP 502 and 10 response-body failures. Reported token totals are 1,411,049 and 1,089,753 respectively. Delivery/cost can be unknown for failed transports. These failures prevent a clean survival comparison. No engine or arena-scope violations were found.

Correction: one authority command now captures the participant context and trace together and retains the supplied evidence for 330 seconds (four reads, 128 experiences each). Initial reads select the latest page; incremental reads remain ordered and explicitly report gaps. Revision, epoch, duplicate, counterpart, expiry and privacy checks remain enforced. Tests cover context/trace consistency, churn, reload, expiry, forged/cross-actor sources and loss of control.

Next is an integration test with four characters per session, reducing simultaneous model pressure while adding tested conserved transfers and shared shelter. Its supplied/shortage pair tests social behavior and meaningful consequences, not the isolated causal effect of the evidence change.
