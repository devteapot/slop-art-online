# Places apart from remembered resources; refusal words (`truthful-refusals`)

Validated on the Spark on branch `truthful-refusals` from `origin/main` `67521779`, the module built from WIP commit `9c5b7463` (authority, rules and mind sources unchanged after it except one doc comment in `brain.rs`). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-truthful-20261122` on `127.0.0.1:3393` with its own `/wasm` mount and volume, CPUs 0-4,10-14. No paid model calls. Changed: the `talk-places` case (the bushes now under "# Resources you have seen[, from where you stand]", none under the places; the think prompt's two sections) and `act-repair` (the refusal now "`go` is not a skill"); `features/conversations.md`.

## Run (`minds-tr-234144`, `--no-unit-tests`; the unit tests ran in `just living-check`)

`talk-places` pass, `act-repair` pass, `acts` pass. Evidence: `.local/living/verify/minds-tr-234144-{talk-places,act-repair,acts}/` (`prompt-talk-1.txt`, `prompt-think.txt`, `talk-places.json`).

Offline: `living-mind` `prompts::tests::places_and_seen_resources_are_apart` (named places and resources apart in think, compile and consolidation; the grammar's place and `at` sentences).

## Not covered

The fast lane's prompt (same grammar text; not driven), player memory's internalize prompt (`verify-knowledge`).
