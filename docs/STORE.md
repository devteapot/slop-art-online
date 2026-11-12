# The store: heavy outputs in one place

Status: **published** (2026-11-11, branch `tool-store-2`, from the Spark).

| Dataset | Holds | Address |
| --- | --- | --- |
| `carlid/slop-art-online-runs` | 62 trial batches, as `batches/spark/<batch>/`: the fake `hm1`, `l9` and 60 more real batches (527 instances, 212,758 model calls, 935,249 rows, 1,192 prompts); play-test 2's session as `sessions/spark/playtest-2/` (133 calls, 5 prompts) | <https://huggingface.co/datasets/carlid/slop-art-online-runs> |
| `carlid/slop-art-online-assets` | the motion library, as `motion/raw/`: 645 Kimodo takes and `batch_stats.json`, plus the skeleton file `motion/somaskel77_skeleton.json`, with `motion/MANIFEST.json` (626 takes on 2026-11-11; 19 added, 2 starts replaced and the skeleton added on 2026-11-12) | <https://huggingface.co/datasets/carlid/slop-art-online-assets> |

**Checks.**
- **Fetch-backs.** `l9` came back byte-identical to the local pack. Unpacked, all 170 files equal the scrubbed source byte for byte. Play-test 2 came back byte-identical to its scrubbed tree (38 of 38 files). The motion library, as first published on 2026-11-11, came back with every sha256 matching: 626 takes byte-identical, and `batch_stats.json` equal as JSON (one trailing newline added by the scrubber).
- **Viewer.** It converted all six tables (`instances` 527, `calls` 212,758, `rows` 935,249, `prompts` 1,192, `session_calls` 133, `session_prompts` 5): row counts equal to the packs' manifests, nothing failed, and the previews, search and filter are on (checked 22:03). The first conversion of `calls` had failed ("Couldn't cast array of type string to null") because `hm1`'s `error` column is null throughout. The card now declares every column's type (`dataset_info`). The assets dataset has the viewer off, since its takes are binary.
- **Held.**
  - `b2`, `b3`: calls from `gpt-6-luna`, held until the owner says which account the proxy uses. `b1` has no Luna call: see [Model terms](#model-terms-who-may-publish-whose-words-read-2026-11-12), Decisions.
  - `aborted` in `~/dev/slop-trials-cb`: no `batch.json`.
  - Play-test 2's 22 non-record files (rule A, listed in its `MANIFEST.json`).
  - Play-tests 3 and 4 are on the laptop.

Publishing stays gated: `publish_enabled` is on only on the Spark, and `publish_sessions` was on only for play-test 2's upload.

## Why

The heavy outputs sit on three disks: run journals and results, play sessions, verification evidence, the motion library and its raw takes, clip handoffs, and the asset board's media. They move between machines by `scp`, `rsync` and hand-made tarballs. Evidence was lost twice when a worktree was removed. The owner suggested public Hugging Face repositories, since the code repository is public and MIT.

| Part | Command | Script |
| --- | --- | --- |
| What a machine holds | `just living-store manifest [--md FILE] [--json FILE]` | [`living/tools/store.py`](../living/tools/store.py) |
| What would be published, with every redaction | `just living-store scrub --dry-run SRC [--report DIR] [--decide CAT=VALUE]` | same |
| Pack a unit as it would be published | `just living-store pack batch\|session\|motion SRC --out DIR` | same |
| Publish (gated) | `just living-store publish batch\|session\|motion SRC --backend local\|hf [--yes-publish]` | same |
| Fetch | `just living-store fetch motion-library`, `just living-store fetch batch NAME [--unpack]` | same |
| Size and file estimates | `just living-store layout [--manifest FILE] [--ratio 0.1]` | same |
| Self-test | `just living-store-selftest` | [`living/tools/store_selftest.py`](../living/tools/store_selftest.py) |

Defaults are in [`living/tools/store_config.json`](../living/tools/store_config.json): never-touch folders per machine, the owner decisions, repository names and backends. Each machine's own settings go in `~/.config/slop-store/config.json` (or `$STORE_CONFIG`). The draft dataset cards are in [`living/tools/store_cards/`](../living/tools/store_cards/).

The tool uses only the Python 3.9+ standard library and runs on Linux and macOS. The Hugging Face backend imports `huggingface_hub` only past its gate, or for a fetch. No other script calls Hugging Face. The machine is detected as `laptop` (macOS), `spark` (Linux aarch64) or `dev-box` (anything else); `STORE_MACHINE` overrides the detection.

This tool reads files that other tools exported and never talks to SpacetimeDB or Neo4j. The SpacetimeDB documentation check in AGENTS.md therefore does not apply.

## Hugging Face facts (checked 2026-11-11)

- **[Storage limits](https://huggingface.co/docs/hub/storage-limits):**
  - Free accounts get "Best-effort" public storage and 100 GB of private storage. Public storage asks for "content that offers genuine value to other users", and the Hub has "mitigations in place to prevent abuse of free public storage".
  - Recommended limits: under 100k files per repository, under 10k entries per folder, under 200 GB per file.
  - "There is no per-repo size limit for models and datasets"; uploads count against the account.
  - Commits: "keep around 50-100 files per commit", and "the user experience on the Hub starts to degrade after a few thousand commits".
  - A dataset needs a card and is shared "to enable community reuse".
- **[Data files](https://huggingface.co/docs/hub/datasets-data-files-configuration) and [adding datasets](https://huggingface.co/docs/hub/datasets-adding):**
  - Accepted: Parquet (recommended), JSON Lines, CSV, WebDataset `.tar` and media.
  - Accepted compression: `.gz`, `.zst`, `.bz2`, `.lz4`, `.xz`, `.zip`.
  - Several tables in one repository: `configs:` entries in the card's YAML, each with `data_files` globs.
  - The pages recommend JSON Lines for nested data. They do not say whether the viewer previews compressed JSON Lines; that is checked on the first upload.
- **[Dataset cards](https://huggingface.co/docs/hub/datasets-cards):** YAML metadata (`license`, `pretty_name`, `tags`, `task_categories`) and a README documenting use and biases.
- **[Uploads](https://huggingface.co/docs/huggingface_hub/guides/upload):** `upload_folder` splits large folders into several commits by itself. Even so, the HF backend commits at most 100 files at a time (`HFBackend.COMMIT_FILES`).

## Manifest

`store.py manifest` scans each checkout's `.local/living` (trial batches, journals, verification evidence, build folders, play sessions), `.local/kimodo/outputs/library`, `.local/play*` and `living/game/assets/lookdev`. In the home folder it scans `playtest-*`, `trials-archive`, `kimodo-test/library` (read only), `cliplab*`, `clip-handoff`, `kimodo-clips-*`, `kimodo-locomotion-*` and `archive/asset-board`. Checkouts are `~/dev/*` and `~/.t3/worktrees/*/*`.

For each item it records the path, size and file count, whether it can be regenerated and in how long, and where it would go. Never-touch folders are listed but not read.

### Spark (2026-11-11 19:30)

Full table: [`docs/store/manifest-spark.md`](store/manifest-spark.md).

| Kind | Items | Distinct units | Size | Files | Regenerable | Goes to |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `trial-batch` | 198 (incl. runner logs) | 97 | 5.7 GB | 18,165 | 64 real (5.1 GB): no, real model calls and hours of run time. 32 fake (452 MB): yes, in their run time | runs |
| `trials-archive` | 50 | 50 | 531 MB | 50 | no; 49 of the 50 are also live batches | runs, deduplicated |
| `trial-ledger` | 15 | 7 | 0.4 MB | 57 | no | runs |
| `journal-copy` | 11 | 10 | 4.2 GB | 5,416 | duplicate: `trials.py` copies each into its batch | not uploaded |
| `mind-journal` | 2 | 2 | 0.2 MB | 10 | no | runs (verify) |
| `verify-evidence` | 16 | 14 | 1.4 GB | 15,252 | mostly yes with the same commit; paid tiers no | runs (verify) |
| `play-session` | 2 | 2 | 120 MB | 399 | no | runs (sessions) |
| `motion-raw` | 1 | – | 115 MB | 151 | partly: same prompt and seed, 3–4 s a take; bit-identical not guaranteed | assets |
| `motion-library-copy` | 1 | – | 455 MB | 627 | as above (a superset of `motion-raw`) | assets |
| `cliplab` | 2 | 2 | 437 MB | 772 | scores yes; takes as above | assets |
| `clip-handoff` | 1 | – | 85 MB | 22 | yes, seconds | assets |
| `clip-deliverable` | 8 | 8 | 577 MB | 939 | yes, seconds | not uploaded (superseded) |
| `trial-build` | 36 | – | 986 MB | 164 | yes: `trials.py build`, minutes | not uploaded |
| `build-output` | 10 | – | 11.2 GB | 22,591 | yes: cargo, minutes | not uploaded |
| `secret` | 13 | – | 715 B | 13 | n/a (`neo4j.env`) | never |
| `other` | 24 | – | 3.5 MB | 167 | mostly yes | case by case |
| `never-touch` | 4 | – | not read | – | n/a: `~/dev/slop-art-online`, `~/slop-lab`, `~/ComfyUI`, `/var/lib/docker` (the `sao-living` data) | never |

25.7 GB was scanned. Of that, 11.2 GB is Cargo output and 4.2 GB is journal copies. The asset board's media are not on the Spark; its records are in git (`living/assets/board/`).

### Adding the laptop and the dev-box

The coordinator on each machine runs these commands from a checkout of `main` once this branch is merged, or of `origin/tool-store` before:

```bash
# laptop (macOS; the main checkout ~/dev/slop-art-online is a normal evidence location there)
STORE_MACHINE=laptop python3 living/tools/store.py manifest --md docs/store/manifest-laptop.md \
    --json ~/store-dryrun-$(date +%F)/manifest-laptop.json
# dev-box
STORE_MACHINE=dev-box python3 living/tools/store.py manifest --md docs/store/manifest-dev-box.md \
    --json ~/store-dryrun-$(date +%F)/manifest-dev-box.json
```

Then commit the `docs/store/manifest-<machine>.md` file on a branch. Each machine has its own file, so the branches do not conflict.

- If a machine has folders that must not be read, list them first in its `~/.config/slop-store/config.json` as `{"never_touch": {"laptop": ["~/path"]}}`.
- If evidence sits somewhere the scan does not look, report the path so the scan can be extended.

To estimate one repository across machines, run `layout --manifest` on each machine's JSON.

## Layout proposal

Two public datasets, a few files per unit, one commit per unit.

**`slop-art-online-runs`** ([draft card](../living/tools/store_cards/runs.md))

```
batches/<machine>/<batch>/   instances.jsonl.gz  calls.jsonl.gz  rows.jsonl.gz  prompts.jsonl.gz  files.tar.gz  MANIFEST.json
sessions/<machine>/<name>/   (the same six files)
verify/<machine>/<checkout>-<date>.tar.gz
README.md                    the card; configs: instances, calls, rows, prompts, session_calls, session_rows
```

- **Tables.** Each table has one fixed schema, so the viewer can show it.
  - `calls` has one row per model call, with `purpose`, `model`, `tokens`, `latency_ms` and `error` as columns, and the whole journal line as `entry`.
  - `rows` has one row per recorded row (`samples`, `thoughts`, `experiences`, `chronicle`, `graphs`, `mind_rows`, `events`, `census`), with `stream`, `at_ms` and the row as JSON text.
  - `prompts` holds each distinct system prompt once, as the mind's journal does.
- **Analysis records** (since `trials-gate-live`, 2026-11-12). Some records are made from other batches' evidence, such as gate replays and judge items and labels, and have no instances of their own. Such a record is a batch folder whose `batch.json` says `"kind": "analysis"`. It lists its files (with sha256) and declares `models_in_outputs`, the models whose words it carries.
  - `check_batch_complete` accepts it without instances.
  - The declared models go into its manifest's `models`, so the same model gate holds it.
  - Its files sit under `analysis/…` and pack into `files.tar.gz`; the four tables stay empty.
  - First use: `gq1`, the rethink gate's quality test (docs/GATE_QUALITY.md). Its models are verified since 2026-11-12, and its Jev pricing is scrubbed. It is prepared for upload but not uploaded ("Model terms", Decisions).
- **Round trip.** `store.py fetch batch <name> --unpack` rebuilds the `trials.py` evidence layout, scrubbed (the self-test checks it file by file). Running `trial_evidence.py` or `trials.py report` on a fetched batch has not been tried yet.
- **Format.** JSON Lines with gzip is used because it needs no dependencies. Parquet, the Hub's recommended format, can replace it later without changing the layout.

**`slop-art-online-assets`** ([draft card](../living/tools/store_cards/assets.md))

```
motion/raw/<clip>_s<seed>.npz   motion/MANIFEST.json (sha256 per take)
motion/cliplab/<clip>/          checks.json, contact sheets, variants.json
motion/handoffs/*.tar.gz        cliplab.py --handoff batches with their sha256
board/<family>/<version>/       asset board photographs and pages (from the laptop's ~/archive/asset-board)
```

**Estimates from the Spark's manifest.** The packed size of `l9` was measured at 9.5 MB from 99 MB, a ratio of 0.096:

| Repository | Part | Units | Raw | Estimated | Files |
| --- | --- | ---: | ---: | ---: | ---: |
| runs | batches | 97 | 5.7 GB | 0.58 GB | 582 |
| runs | sessions | 2 | 120 MB | ≤ 60 MB | 12 |
| runs | verify | 17 | 1.4 GB | ~0.15 GB | 16 |
| **runs** | | | | **~0.8 GB** | **~616** |
| assets | motion/raw | 627 takes | 455 MB | 455 MB (npz, already compact) | 628 |
| assets | cliplab, handoffs | 3 | 521 MB | ~0.26 GB | ~725 |
| **assets** | | | | **~0.7 GB** | **~1,350** |

- **Within the advice.**
  - Both repositories stay far below 100k files and 10k per folder. The largest folder is `motion/raw`, with 627 files.
  - About 120 commits in all: one per batch or session, and seven of at most 100 files for the takes. That is far from "a few thousand".
- **Unknowns.** The laptop's play sessions, play reports and asset board, and the dev-box's runs, are not counted yet; add them from their manifests.
- **Real against fake.** Publishing only the 64 real batches would make the runs repository about 0.5 GB.

### Not uploaded, and why

| What | Why |
| --- | --- |
| Cargo targets (`target-*`, `verify/build-*`), trial modules (`trials/wasm`), derived seeds (`trials/seeds`), build logs | Build output: regenerated in minutes from the code at the batch's commit (`batch.json` records it). 12 GB on the Spark alone. |
| SpacetimeDB replicas, WAL and the Docker volumes; Neo4j stores | Database replicas. What matters from them is already exported into the batch (rows, `final.json`, snapshots). They are also large and machine-specific. |
| `.local/living/journal/verify-trial-*` | Duplicates of each batch's `journal/` (copied at the stop; checked byte-identical on `l9`). |
| `~/trials-archive/*.tar.gz` that are also live batches | 49 of 50 are. The one archive-only tarball (3.4 KB) would be unpacked to a scratch folder and packed as a batch; `pack` does not read tarballs as batches yet. |
| `kimodo-clips-*`, `kimodo-locomotion-*`, review folders | Hand-made copies of takes that `motion/raw` and `motion/handoffs` hold. |
| `living/game/assets/lookdev` (game-ready GLBs) | `just living-game-assets` regenerates them in minutes. Accepted versions are recorded through the board. |
| `neo4j.env`, `.env`, `cli.toml`, keys | Secrets: refused by the scrubber whatever the source. |
| Browser profiles, `__pycache__`, macOS `._*` files | Not evidence. A browser profile holds cookies and logins. One was found in `~/playtest-2` (`ffprof/`, `review/ffprof-ui/`) and refused. |

## The scrubber

`store.py scrub --dry-run SRC` reads SRC twice, writes nothing outside `~/store-dryrun-<date>/` (or `--report`), and uploads nothing. SRC can be a folder, a file or a tarball; tarball members are read in memory.

1. **Learn.**
   - The session's player comes from the client log's `playing character #N` (or `--player`).
   - The owner's typed lines are found where the world quotes them:
     - `<speaker> said[ to …]: “…” {<speaker>=#N, …}`, where the tags start with the speaker, except after `You said`;
     - a conversation prompt's lines from the label in its `# You and <label> (#N)` header;
     - client events of kind `say`.
   - Logins are taken from home paths (`/home/<x>`, `/Users/<x>`).
2. **Classify and redact.** Each file gets a status:
   - `ok`: publishable after redaction;
   - `held`: waits on an owner decision;
   - `excluded`: the owner said no;
   - `refused`: cannot be made safe;
   - `skipped`: build output.

   Held files are still read, so the report shows their redactions. File names are scrubbed too, for example `Diego.jsonl` becomes `Player.jsonl`.

**Always redacted (text):**

| Category | What | Becomes |
| --- | --- | --- |
| `known-secret` | The literal values of this machine's secrets: secret-named variables in the environment and in every checkout's `.env`, `trials/*.env` (including the password half of `NEO4J_AUTH`), the HF token file and SpacetimeDB CLI tokens. Read at run time, never printed. This is how a bare 32-character Mistral key is caught. | `[redacted:secret]` |
| `hf-token`, `github-token`, `api-key`, `aws-key`, `slack-token`, `google-key`, `jwt` | `hf_…`; `ghp_/gho_/ghu_/ghs_/ghr_…` and `github_pat_…`; `sk-…` and `sk-ant-…`; `AKIA…`; `xox?-…`; `AIza…`; JWTs (SpacetimeDB identity tokens) | `[redacted:<category>]` |
| `bearer`, `secret-assignment`, `url-credentials`, `secret-field` | `Bearer …`; `Authorization: Basic …`; `x-api-key`; `NAME_TOKEN/SECRET/PASSWORD/API_KEY/_KEY/_AUTH=…` (so `LIVING_TOKEN=…`, `MISTRAL_API_KEY=…`); `password=`, `token=` and the like; `scheme://user:pass@`; JSON fields named like secrets (`prompt_cache_key` is not one) | `[redacted:secret]` |
| `owner-email`, `email` | The owner's addresses (git config, `GIT_*`, `STORE_OWNER_EMAILS`), then any address | `[owner-email]`, `[email]` |
| `owner-name` | Full name and surname (git config, `GIT_*`, `STORE_OWNER_NAMES`) | `[owner]` |
| `home-path`, `login` | `/home/<user>`, `/Users/<user>`, `C:\Users\<user>`; bare logins | `~`, `[user]` |
| `private-ip` | 10/8, 172.16/12, 192.168/16, Tailscale 100.64/10 (octets checked; 127.0.0.1 and public addresses stay) | `[private-ip]` |
| `hostname` | This machine's name, `~/.ssh/config` hosts, `STORE_HOSTNAMES`, `*.ts.net`, `*.local`/`*.lan`, Mac default names | `[host]` |

**Jev's pricing** (`jev-pricing`; decision `jev_pricing`, anything but `include` applies it; `jev_strip` and `jev_text` in `store.py`). TypeSafe's Master Customer Agreement s.14.1 counts "all pricing information" as its Confidential Information.
- **JSON and JSON Lines.** In a Jev object, every key naming cost, usd, price or spend is dropped, at any depth. A Jev object is one whose `model`, `profile`, `arm`, `gate`, `url` or `provider` names Jev or `typesafe.ai`, or that sits under a key naming Jev. So these go:
  - a Jev journal entry's `cost_usd`;
  - `input_usd_per_m` in `rethink.json` and `judgments.json` copies;
  - `points.jsonl`'s `jev.cost_usd`;
  - the Jev replay's `judged.cost_usd`;
  - a Jev gate's `usd_per_trigger` and `cost_vs_off` in `curve.json`;
  - `by_model`/`by_purpose_model` Jev cost fields in a summary.
- **Totals.** Under a cost key, a part named for Jev is dropped and a sibling `total` is recomputed without it (`gq1`'s `spend_usd`: 0.765 becomes 0.685).
- **Text.** These become `[removed: Jev pricing]`:
  - in a table row naming Jev, the cells of cost columns;
  - in a line about Jev (it names Jev, or sits under a list item or lead-in paragraph that does), dollar amounts and the percentages of clauses about cost or savings;
  - elsewhere, a cost clause that repeats a percentage removed from a Jev row;
  - in a text naming Jev, the dollar amounts of spend and total lines.
- **Kept.** Other models' costs: GLM gate calls, think and compile calls, `deliberation_cost_usd`, the gate-off and GLM-gate rows.
- **Over-removal.** A cost clause that also carries a harm figure loses it too. "9.2%" in "Jev 0.3 with GLM is 9.2%" stays only because a comma separates it from the cost.

**Refused whole:**
- files in never-touch folders, or with `sao-living` in the path;
- **credential files, never opened** (`is_secret_path`, fbc37c32 review A4):
  - **By file name:** `.env`, `.env.*`, `*.env`, `*.token`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.jks`, `*.kdbx`, `*.secret(s)`, `id_*` keys, `credentials*`, `.netrc`, `.git-credentials`, `.pgpass`, `.npmrc`, `.pypirc`, `cli.toml`, `hf_token`, `token`.
  - **By folder:** anything under `tokens/`, `secrets/`, `.ssh/`, `.gnupg/`, `.aws/`, `credentials/`.
  - **Never read:** the check runs on the path before anything is read. On disk the loader is a stub that refuses if called, and a tarball member matching these names is listed but never extracted.
  - **Listed as held:** with the reason "secret path, not read", in the report and the manifest's `held` section.
  - **Exception:** the scrubber's own identity step still reads this machine's checkout `.env` files and token files on purpose, to learn the secret *values* to redact (`Identity.from_runtime`). That is not part of reading the source, and the values are never printed.
- anything containing a private-key block;
- browser profiles;
- macOS metadata;
- binaries of unknown kind.

Known binaries (`.npz`, images, video, `.glb`) are scanned as bytes for literal identity strings, home paths and token patterns. A hit refuses the file, because it cannot be redacted in place.

No identity is in the repository: the scrubber reads it at run time, and the tests plant fake values. The owner's identifiers are not hard-coded either.

**Self-test** (`just living-store-selftest`, 62 tests on 2026-11-12, under a second):

- planted secrets in every format above, including a bare Mistral-style key, `LIVING_TOKEN` in shell and JSON form, `NEO4J_AUTH`, a SpacetimeDB-style JWT and URL credentials;
- the owner's email, name, first name and login;
- private and non-private addresses, hostnames, and base64 that must not match;
- strings that must stay unchanged (`.local/living`, journal hashes, `prompt_cache_key`, `max_tokens`, "the bearer of the letter");
- refusals, never-touch paths, gzip and JSON Lines;
- a fake play session: the owner's lines are learned and redacted, a resident's line to the player is kept, and the browser profile is refused;
- the dry-run CLI, checking that no secret reaches the report or stdout;
- batch pack → local publish → fetch → unpack, equal to the scrubbed source;
- the motion round trip with sha256 checks;
- the manifest on a fake home;
- the publish gate;
- Jev's pricing (`JevPricing`): each kind of record `gq1` holds, with distinctive planted figures. Each Jev figure is gone from every packed file, the manifest included. Other models' costs stay, `spend_usd`'s total is recomputed, the report shows no figure, and `jev_pricing: include` keeps everything.

### Dry runs (2026-11-11; reports in `~/store-dryrun-2026-11-11/` on the Spark, not in git)

| Source | Files ok | Held | Refused / skipped | Redactions (masked) |
| --- | --- | --- | --- | --- |
| Trial batch `l9` (`~/dev/slop-trials-e6/.local/living/trials/l9`, read only, 99 MB, 6 instances) | 134 (50.9 MB) | 36 journal files (46.6 MB): `model_exchanges` | 0 | `home-path` 18 (`/home/g…`), `secret-field` 6 (`…[16 chars]`: the fake-server key in `mind-env.json`) |
| Play-test 2 (`~/playtest-2`, 121 MB) | 249 (67.6 MB) | 101 (23.7 MB): 62 journal files, 37 stills/screenshots, 2 FEEDBACK.md | 163 refused (95 browser profile, 68 macOS `._*`), 8 skipped (`__pycache__`) | `home-path` 514 (`/Users/c…`, `/home/g…`), `owner-first-name` 554 (`D…o[5]`), `owner-line` 240 (`w…p[6]`, `h…`, `s…i[11]`) |
| Play-test 3 (`~/playtest-3`, two tarballs) | 37 (1.7 MB) | 66 (2.8 MB): 64 journal files, 2 FEEDBACK.md | 117 macOS `._*` | `home-path` 8, `owner-first-name` 98, `owner-line` 37 (`H…`) |

- **Secrets.** None of the three sources holds an API key, token, JWT, private address or owner email.
- **Owner lines, play-test 2.** The scrubber found exactly the owner's three typed lines (masked `h…`, `s…i[11]`, `w…p[6]`), the same lines as the hand-made diagnosis `playtest-2/diagnosis/REPORT.md`.
- **Owner lines, play-test 3.** Up to fbc37c32 the scrubber learned **two** lines there, not one. The extra is a line the owner's character said under its AI mind after the session ended: an authority row of the player (`subject` 26), timestamped 55 s after the client log's last line. The "You said" row rule assigned it to the owner. That was harmless over-redaction. Since `fix-store-scrub-2`, `You said` rows with a time count only inside the played span: the client log's first to last timestamp, from 1 s before to 5 s after. That row is now left alone, so play-test 3 should learn one line. This was not re-run here, by instruction.
- **Packed size.** The `l9` what-if pack (`--decide model_exchanges=include`) is 9.5 MB. No home path, login, hostname or fake key is left in it.

### The owner's decisions (2026-11-11)

The owner agreed to publish, publicly, under the personal namespace `carlid`, on these terms. They are recorded in `store_config.json` (`decisions`):

| Category | Decision | Effect |
| --- | --- | --- |
| `model_exchanges` | **include** | Journals are published with the redactions above. |
| `owner_lines` | **exclude** | Each line is replaced by `[owner line]` wherever it recurs. In play sessions, the echo pass below also drops whatever quotes or repeats one. |
| `owner_first_name` | **redact** | Replaced by `Player` (`player`, `PLAYER` to match the case), in file names too. |
| `owner_notes` | **hold** | Not published; the rest of the unit still is. |
| `session_media` | **hold** | Not published. |
| `jev_pricing` (2026-11-12, general coordinator) | **exclude** | TypeSafe Jev's price, per-call costs and share of totals are removed (below), until the owner confirms they may be shown. |
| Models' words in world rows | **kept** | – |
| Licence of both cards | **MIT** | – |

`hold` is a decision value: such a file is listed as excluded and does not block its unit. `undecided` still blocks it. `--decide CAT=VALUE` previews a choice on `scrub` and `pack` without saving it.

Not redacted, by design:
- SpacetimeDB identities (public keys, not credentials);
- the code repository's GitHub URL;
- residents' names, which are game content.

### Owner-line echoes (play sessions)

Exact quotes were not enough. On play-tests 2 and 3, models repeated the owner's lines:
- in single quotes ("Don't 'wassup' me", "the stranger who said 'hi'");
- as variants ("babbles nonsense ('sssshi', …)" for "ssssssssshi");
- unquoted after a verb ("Said hi, then set on my mother");
- as a JSON value (`"what": "Hi"` in the player's own memory).

Lines no one heard can sit in the player's own percepts ("You said to a child: “…”").

What the scrubber does now:
- **Learning.** Besides the rules above, `You said …: “…”` counts as the owner's line in the player's own entries (`(played by a person`, `# Who you are (<player>)`) and in rows whose `subject` is the player, if the row's time is inside the played span.
  - The player's own entries carry no real time; their percepts show game time only. So a line the character's AI mind said there after the session can still be learned: over-redaction, not a leak.
- **Exact matches.**
  - Any quote style counts: typographic, single, back-quote, escaped, or HTML entities (`&ldquo;`, `&quot;`, `&#39;`), in any case. So does a JSON string equal to a line.
  - The match uses the line's **core**: leading and trailing whitespace and punctuation removed, and internal whitespace of any width. "where am i ?" therefore matches “where am I?”, “Where  am i” and, being 6 characters or more, an unquoted "where am I" (fbc37c32 review A3).
- **Names the player gave themself** (fbc37c32 review A2; narrowed in `fix-store-scrub-3` after play-test 4 v2).
  - **Learned from what residents recorded, checked against what the player typed** (`fix-store-scrub-4`, after play-test 4 v3 learned nothing from `i'm called ""N""`):
    1. **Candidates.** Every name residents hold for the player's *character*, tied to it by its id:
       - the name on that person in residents' memory graphs (`name`, `known_name`, `known_as`, `introduced_as`, `nickname` and similar), including graphs inside model replies stored as JSON text, as escaped or doubly escaped JSON, or as `\uXXXX`-escaped text;
       - residents' tags (`{N=#26}`) and labels (`N (#26)`, `N (person:26)`);
       - name fields near the id in logs.

       The player's own record (player memory, "played by a person") is not a resident's.
    2. **Kept** as the player's self-given name only if the same word also occurs in one of the player's own typed lines in that session: case-insensitive, ignoring quotes and punctuation. No phrase pattern is needed.
    3. **Never learned:** a name residents hold that the player never typed (an epithet): it stays.
    4. **An extra source:** the typed self-introduction patterns (`SELF_NAME_RULES`: "I'm N", "i'm called N", "call me N", "they call me N", "named N", "the name's N", …, with stray, doubled or mixed quotes) still add a name residents do not hold.

    The backstop is `names.md` and `report.json` (`names`): every name residents hold for the player, masked to its length, with who holds it in records (graphs, tags, labels), where, how often each holder uses the word in speech, journals and logs (`Uses by holder`; the player's own record is counted separately and templates not at all), whether the player typed it, and what was done (replaced, or kept and why). In the review files the `self-name` and `self-name-kept` categories, like every identity category, show only a length (`[6 chars]`). If the player's character id is not found, the report says so and no resident-held name is tied to the player.

    On this machine, play-tests 2 and 3 each have 3–4 resident-held names. None was typed by the player except the owner's first name, so nothing new was learned, and both outputs are byte-identical to v3.
  - **The owner's real first name** is still replaced everywhere, in any case.
  - **A self-given name can also be an ordinary game word** (in play-test 4 it was), so it is replaced only where it names the player:
    - **Never in text the game or the mind service wrote from a template:** system prompt files, system messages inside journal entries, installed scripts, `*.rhai`. These stay byte-identical, and an owner line quoted into them is still caught by the exact quoted match. Nor in JSON keys, game codes (`do`, `skill`, `kind`, … in `CODE_KEYS`), or identifiers (`on_strike`: here `_` joins words).
    - **Replaced as a name:** after "called", "named", "introduced (themself) as", "goes by", "known as", "call me", "I'm", "calling/called himself" (and herself, themself, themselves), "self-styled", "styles himself"; in `known_name`, `known_as`, `introduced_as`, `nickname` and `name` fields (the name on the person, and memories about them); in `{X=#26}` tags and `X (#26)` labels; as an address at the start of a line or utterance ("X, come here"); capitalised, not at the start of a sentence ("I told X about the well"); in file names.
    - **Kept as the ordinary word, silently:** lowercase after an article, possessive or determiner ("a strike", "the strike"), when the word also occurs in this run's game-written text (templates, system prompts, installed scripts).
    - **Kept as the ordinary word, and listed** (`fix-store-scrub-5`, D2): any other lowercase use right after a possessive ("Mercy's word", "his word", "my own word") or an article ("the word"). It is listed in `ambiguous.md` as kept, with that reason. In play-test 4 v4 this keeps 3 of the 4 ambiguous places in Maud's journal.
    - **Undecidable, so replaced and listed:** every other use in residents' speech and journals ("strike them down", a capitalised word at a sentence start). Each entry goes to `ambiguous.md` and to `report.json` (`ambiguous`), with the file, the location (row, field path, line), the context with the name masked by its length (`[6 chars]`) and the replacement. A wrong replacement there costs one word. The manifest records only the count (`self_name_ambiguous`).
- **The installed rules script is a hard check** (`installed_sha_problems`). If a session records `installed sha256 …` in `run/installed_script.txt`, the published `installed_source.rhai` must hash to it, so the record stays verifiable. Older records have no `installed_source.rhai` and instead name their file on a `file sha256 … (…/skills.rhai)` line; that file is checked. `pack` and `publish` refuse a unit that fails, before writing anything. `scrub` writes its reports, prints MISMATCH, and exits non-zero, giving why: the script is not published, or which redactions changed it. `installed_script.txt` itself may change, but only where its home paths are redacted (`/Users/<login>/…` becomes `~/…`); the shas it records stay as they are.

  Checked on this machine's sessions (outputs kept locally in `~/store-dryrun-2026-11-11/playtest-{2-v3b,3-v3}/`):
  - Play-test 3: the installed sha matches; all 6 system prompts and `installed_source.rhai` are byte-identical; `installed_script.txt` differs only by the home path.
  - Play-test 2: the record names `skills.rhai`, and its sha matches, both in this scrub and in the copy already published.
  - Neither session has a self-given name, so there are 0 ambiguous places.
  - Play-test 2's scrub is byte-identical to the published unit (38 of 38 files).
- **Echo matcher** (`EchoMatcher`):
  - Letter runs are folded (`ssssssssshi` and `sssshi` are both `shi`).
  - A one- or two-word line matches a word that is equal after folding, or within edit ratio 0.8 for words of four letters or more.
  - A common word ("hi", or anything of three letters or fewer) counts only when quoted alone or within two words after a speech verb. So a resident's own "Hi! Are you new here?" stays. `say` is not a speech verb, because it is the JSON key in front of every spoken line.
  - A longer line matches a window sharing at least 60% of its words (at least three), or reading 80% alike. The window must also share at least two of the line's **distinctive** words, totalling 8 letters or more. Distinctive means not in the stop-word list (`STOPWORDS`) and 3 letters or more. So a line of common words ("I can see it") is caught only when repeated exactly, and never in "you can see it" (fbc37c32 fix).
  - **Templates are never fuzzy-matched.** The system prompt files (`journal/system/*.txt`), system messages inside journal entries, installed scripts (`installed_source*`, `installed_script.txt`) and `*.rhai` are written by us, not the owner. An owner line can reach them only by substitution, in quotes, so they get the exact quoted match only: no unquoted match, no echo, no dropped lines.
- **What is dropped.** In a play session, a journal entry whose reply quotes or echoes an owner line is dropped whole, and so is any world row (JSON Lines) that does. A text line that does is replaced by `[line dropped: it quotes or repeats an owner line]`. Echoes inside prompts and JSON files are replaced by `[owner line]`.
- **Command histories keep their rows.** A row of `commands.jsonl` or `events.jsonl`, or any row whose `cmd`/`kind`/`reducer` is a say, is kept with its timestamp. Every string in it that holds or echoes an owner line becomes `[owner line]`. `dropped.md` lists it with the action "kept, text replaced".
- **File names.** Any word of a file name that echoes an owner line, even a common one, becomes `owner-line` (`journal_cuth_reply_hi.txt` becomes `journal_cuth_reply_owner-line.txt`).
- **Report pages.** These (`*.html`) are excluded from session units: `play_report.py` regenerates them from the evidence.
- **The list.** Everything dropped is listed in `dropped.md` and the unit's `MANIFEST.json`, without the owner's text.

Results on play-test 2 (the session evidence, `~/playtest-2/data/playtest-2`):
- 4 journal entries and 60 text lines dropped;
- 98 exact owner-line redactions, 2 echo redactions, 95 first-name replacements;
- afterwards, no form of the three lines (`hi`, `ssssssssshi`, `wassup`), and none of the owner's names, logins, host or home paths, remains in text or file names.

On play-test 3, 3 journal entries were dropped (two from the player's own memory, one consolidation repeating "Hi" three times).

What remains exposed:
- **Semantic paraphrase.** "A stranger said hello" for "Hi": the model's words, carrying only the fact of a greeting.
- **Unheard lines outside the player's memory.** Lines no resident heard, and that are not in the player's memory, are not in this evidence at all. These sessions predate the client recorder; newer sessions log every line sent in `events.jsonl`, which the scrubber reads.

Sessions stay held (`publish_sessions` is off) until the general coordinator has reviewed the scrubbed output of play-test 2.

### Play sessions: what is published

A play session publishes an **allow-list**: the record of the run, not analysis of the person who played. `session_allowed()` in `store.py` admits only these files:
- `session/journal/*.jsonl`, `session/journal/system/*.txt`, `session/journal/batches/*.json`;
- `session/run/*.log`, `*.jsonl`, `*.txt`, `*.rhai` and `created_utc`;
- `session/skills.rhai`;
- `session/README.md`, but only if it does not describe the owner. It is held if it names the owner or a login, or uses words like *owner, you, your, feedback, play-test, wants to, intends*.

Everything else is held and listed, with its reason, in the unit's `MANIFEST.json` (`held`):
- anything outside `session/`: `diagnosis/` and any folder like it, `FEEDBACK.md`, reports, pages;
- checklists and notes for the owner (`session/CHECKLIST.md`);
- media;
- file types not on the list.

Feedback was held by the owner's decision. The rest is agents' analysis of what the owner did and meant: analysis of a person, not a record of a run.

Held files are still read to learn the owner's lines. A client recorder's `events.jsonl` therefore teaches the scrubber every line sent, even though the file itself is not published.

**Review-only files.** A session's `report.json` and `commands.jsonl` (`SESSION_REVIEW_NAMES`) are scrubbed in the same pass. `scrub --write DIR` writes them under `DIR/review/`, so no second pass with `--kind generic` is needed. They are listed as `review` in the reports and in the manifest's `held` section. They are never packed or published unless the general coordinator later approves.

**Review files are redacted like published content** (fbc37c32 fix):
- `report.md`, `report.json`, `dropped.md` and stdout pass every path and string through the published redaction. Paths appear as they would be published.
- The source is named home-relative (`~/…`), or by its last two folders if it lies outside home, redacted too.
- Masked examples of identity categories (names, logins, owner lines and echoes, host names, emails) show only a length, `[5 chars]`; home paths show `/home/…`.
- The self-test `ReviewOutputs` searches every output, file names included, for the planted owner names, login, email and lines.

Review folders written before this fix (in `~/store-dryrun-2026-11-11/` on the Spark) still list raw source paths. They are local only, and nothing published was affected.

Play-test 2 under the allow-list: 38 files published (the journals, `session/run/`, `skills.rhai`). 22 held: `FEEDBACK.md`, all 20 files of `diagnosis/`, `session/CHECKLIST.md`, and `session/README.md`, which describes the owner's session.

### Publishing from the laptop or the dev-box

The steps are the same on every machine. The gate is per machine and per upload.

1. **Code.** A checkout at `origin/main` once `tool-store-2` is merged, or at `origin/tool-store-2` before.
2. **Library.** `huggingface_hub` in its own venv, used only for publishing:
   ```bash
   python3 -m venv ~/.slop-store-venv && ~/.slop-store-venv/bin/pip install huggingface_hub
   ```
   `just living-store` runs the venv's Python when it exists, and `python3` otherwise. Without the library, a Hugging Face publish or fetch is refused as soon as the gate passes, before anything is packed, and the message names the venv. On 2026-11-12 the Spark had no venv: the `gq1` upload got through its checks and failed at the import, with nothing sent. The venv was recreated with `huggingface_hub` 2.4.0.
3. **Token.** `~/.config/slop-store/hf_token`, mode 600. It is already installed; check it with `stat -f %Lp ~/.config/slop-store/hf_token` (macOS) or `stat -c %a …` (Linux). The tool reads no other token.
4. **Dry run first, and read it.**
   ```bash
   STORE_MACHINE=laptop python3 living/tools/store.py scrub --write ~/store-dryrun-$(date +%F)/<name>-scrubbed <session folder> --kind play-session
   ```
   Then check:
   - `report.md`: `owner_lines.distinct_lines` must equal the number of different lines typed in the session (the masked examples show only each line's length);
   - `review/`: the scrubbed `report.json` and `commands.jsonl`, held from publishing;
   - `dropped.md`: what the echo pass removed;
   - the `excluded` rows: what is held and why.

   The session folder is the one holding `session/` (for example `.local/living/playtest-3`). Send the general coordinator the `-scrubbed` folder and wait for approval.
5. **Open the gate, for this upload only.** Write `~/.config/slop-store/config.json`:
   ```json
   {"publish_enabled": true, "publish_sessions": true, "backends": {"hf": {"namespace": "carlid"}}}
   ```
6. **Publish.**
   ```bash
   STORE_MACHINE=laptop ~/.slop-store-venv/bin/python living/tools/store.py publish session <session folder> --name playtest-3 --backend hf --yes-publish
   ```
   It goes to `carlid/slop-art-online-runs` under `sessions/laptop/playtest-3/`.
7. **Close the gate.** Set `"publish_sessions": false` (or remove the file) straight after.
8. **Check on the site.** Look at <https://huggingface.co/datasets/carlid/slop-art-online-runs/tree/main/sessions>. Then `fetch` the session back with `fetch` and compare it with the `-scrubbed` tree.

Trial batches follow the same steps with `publish batch <batch folder>`, or `publish-batches --list FILE --stage DIR` for many in a few commits. `publish_sessions` is not needed for them. A batch with any call from a model not verified in `store_config.json` (`models`) is refused.

## Licences (draft notes; not legal advice)

| Data | Derives from | May it be published? | Source |
| --- | --- | --- | --- |
| Kimodo motion takes (`motion/raw`) | NVIDIA Kimodo-SOMA-RP-v1.2 (NVIDIA Open Model License), trained on the proprietary Bones Rigplay dataset; prompts encoded by Meta Llama 3 8B Instruct through LLM2Vec | Yes, as far as read. "NVIDIA does not claim ownership to any outputs"; "An output is not a Derivative Model"; "You are responsible for outputs and their subsequent uses" (ss. 1.1, 2.4). Redistribution terms bind copies of the model, not outputs. Model use must follow NVIDIA's Trustworthy AI terms. Llama 3: "Built with Meta Llama 3", and s.1.b.v forbids using its "output or results" to improve another LLM; the card asks users not to train language models on the takes. | `~/kimodo-test/kimodo/README.md` (code Apache-2.0; checkpoints licensed separately); the model's `LICENSE` and `README.md` in the local HF cache (read only); [model page](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2); [licence page](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) (version of 2025-10-24); the Llama 3 `LICENSE` in the local HF cache |
| VRoid sample characters (`vroid-Sendagaya_Shino`, `vroid-Vivi`) | VRoid beta samples, downloaded by `living/tools/lookdev_assets.sh` from the `madjin/vrm-samples` mirror | CC0 with commercial use allowed: each file's VRM metadata reads `licenseName: CC0`, `commercialUssageName: Allow`, `allowedUserName: Everyone`. They are not in the proposed repositories; our generated characters contain none of their content. | [`living/tools/blender/THIRD_PARTY.md`](../living/tools/blender/THIRD_PARTY.md) (read from the files 2026-11-11); [OpenGameArt "VRoid Studio CC0 models"](https://opengameart.org/content/vroid-studio-cc0-models). VRoid's own help and Hub pages refused automated reads (HTTP 403). A [Booth listing](https://booth.pm/en/items/3094418) says VRoid has ended distribution of the CC0 samples. |
| Model replies (journals, thoughts, spoken lines) | Mistral AI's API serving `zai-glm-5-3-flash`, `deepseek-v4-1-flash-1017` and `ministral-*` | Probably yes, labelled AI-generated. Mistral's [Commercial Terms](https://legal.mistral.ai/terms/commercial-terms-of-service) (effective 2026-09-25): the customer "owns all Output" (s.3.1). It may not be presented as human-made (s.3.2) or used to reverse engineer Mistral's products (s.2.2(e)). [Additional terms](https://legal.mistral.ai/terms/additional-terms) s.6 leave third-party models' rights with their licensors. [GLM-4.5](https://huggingface.co/zai-org/GLM-4.5) is MIT. [DeepSeek's model licence](https://github.com/deepseek-ai/DeepSeek-V3/blob/main/LICENSE-MODEL) s.6: "DeepSeek claims no rights in the Output". DeepSeek's own [platform terms](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html) ask that published output be marked as AI-generated (s.3.1), which the card does. | Superseded by [Model terms](#model-terms-who-may-publish-whose-words-read-2026-11-12) (2026-11-12), which settles the versions and `-latest` aliases below. Earlier note: **not verified:** the licences of the exact GLM 5.3 and DeepSeek V4.1 versions, and whether `ministral-*-latest` maps to Ministral 3 (Apache-2.0 on its [8B card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512)) or the 2410 models ([Mistral Research License](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410)). `l9` used only GLM and DeepSeek. |
| Prompts and world rows | Our mind service and the authority's rules | Ours, MIT | this repository |
| Blender-generated models, textures, board photographs | Our scripts and the game's renderer | Ours, MIT. The tools (Blender GPL, ffmpeg LGPL/GPL) put no terms on what they produce. | `living/tools/blender/THIRD_PARTY.md` |
| SpacetimeDB exports, Neo4j data | Data written by our module and minds | Yes. [SpacetimeDB](https://github.com/clockworklabs/SpacetimeDB/blob/master/LICENSE.txt) is BSL 1.1 (changing to AGPL-3.0 with a linking exception) and [Neo4j](https://github.com/neo4j/neo4j/blob/dev/LICENSE.txt) Community is GPLv3; both cover the programs. Neither says anything about exported data; the GPL family covers output only when the output is itself a covered work. Replicas and stores are not published anyway. | the linked licence files |

The proposed licence of both cards is MIT, matching the code. That is the owner's choice; the cards are marked draft.

### Model terms: who may publish whose words (read 2026-11-12)

The owner allowed model exchanges in published runs (`model_exchanges: include`). This section checks only that no provider forbids publishing outputs. It is a reading of the terms, not legal advice. It changes neither the gate (`store_config.json` `models`, `check_models`) nor any batch's publish state.

**Models in our run records.** All journals under `~/dev/*/.local/living/trials` on the Spark, by the `model` field: `zai-glm-5-3-flash` 421,187 calls, `deepseek-v4-1-flash-1017` 102,558, `mistral-small-latest` 2,204, `jev-1.14.0` 556 plus `jev` 341, `gpt-6-luna` 474, and the fake server's `fake-*` names. `ministral-*-latest` appears only as `fake-ministral-*`. The `gq1` analysis record also declares `claude-opus-5-5`, 768 judge labels, in `models_in_outputs`. Laptop sessions were not scanned.

**Routes, from the configs.**

| Name in records | Model | Route | Source |
| --- | --- | --- | --- |
| `zai-glm-5-3-flash` | Z.ai GLM 5.3 Flash | Mistral API, `https://api.mistral.ai/v1`, `MISTRAL_API_KEY` (profile `glm-flash`) | `living/configs/models.json` |
| `deepseek-v4-1-flash-1017` | DeepSeek V4.1 Flash 1017 | Mistral API, same key (profile `deepseek-flash`) | same |
| `mistral-small-latest` | Mistral Small 4 (`mistral-small-2603`), see below | Mistral API (profile `mistral-small`, `b1`–`b3`) | `models.json` at `af8332d`; each `b2` instance's `models.json` |
| `jev-1.14.0`, `jev` | TypeSafe Jev | TypeSafe API, `https://api.typesafe.ai/v1/systemone`, `TYPESAFE_API_KEY` | `living/configs/rethink.json`, `judgments.json` |
| `gpt-6-luna` | an OpenAI model, as the proxy reports it | the owner's proxy `https://codex.carlid.dev/v1` (`CARLID_NPC_API_KEY`), the `codex-cursor-proxy` translating Chat Completions to an upstream Responses API | `models.json` at `af8332d`; `PROXY_TOKEN_LIMIT_FINDING.md` and `CARLID_ENDPOINT_SETUP.md` at `legacy-baseline` |
| `claude-opus-5-5` | Claude Opus 5.5 | Claude Code subagents on the owner's Claude Max subscription (OAuth sign-in, no API key; "cost nothing in API money") | `gq1/batch.json` (`judges`); [GATE_QUALITY.md](GATE_QUALITY.md); the Spark's Claude Code account type `claude_max` |

#### Mistral API: GLM 5.3 Flash, DeepSeek V4.1 Flash, Mistral Small 4 (and Ministral 3)

- **Terms.** [Commercial Terms of Service](https://legal.mistral.ai/terms/commercial-terms-of-service), effective 2026-09-25; [Additional Terms](https://legal.mistral.ai/terms/additional-terms), effective 2026-09-25; [Usage Policy](https://legal.mistral.ai/terms/usage-policy), effective 2026-06-11; [models list](https://docs.mistral.ai/models). Read 2026-11-12.
- **Ownership (s.3.1).** "To the extent permitted by applicable law, Customer (i) retains all ownership rights in Customer Data and (ii) owns all Output. Mistral AI hereby assigns to Customer all right, title, and interest, if any, in and to Output that Mistral AI may have."
- **Third-party models (Additional Terms s.6).** "All right, title, and interest in and to each Third-Party Technology remains with its respective licensors. Third-Party Technologies are provided "as is" … under their respective licenses". And: "With respect to any Output generated using a Third-Party Technology, Mistral AI assigns to Customer all right, title, and interest, if any, that Mistral AI may have in and to such Output."
- **Sharing.** No clause forbids publishing text Output. The conditions are:
  - s.3.2: "Customer may not represent or imply that the Output was generated by a human when it was generated by the Mistral AI Products."
  - s.3.5: "always verify the reliability, accuracy, and completeness of the Output before relying on it for any purpose or otherwise making it available to third parties." That is advice; it states no ban.
- **Attribution.** None asked, beyond not presenting Output as human-made.
- **Training and redistribution.**
  - s.3.3 limits only images: "Customer may not use image Outputs to develop or train any image generation product that competes with a Mistral AI Product."
  - s.2.2(d), (e): no using Output "to reverse engineer the Mistral AI Products".
  - No limit on redistributing text Output.
- **The models' own licences (Mistral's models list and model pages).**
  - `zai-glm-5-3-flash`: "Z.ai GLM 5.3 Flash", MIT. The [HF LICENSE](https://huggingface.co/zai-org/GLM-5.3-Flash/raw/main/LICENSE) is MIT, "Copyright (c) 2026 Z.AI Co., Ltd".
  - `deepseek-v4-1-flash-1017`: "DeepSeek V4.1 Flash 1017", MIT. The [HF LICENSE](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/raw/main/LICENSE) is MIT, "Copyright (c) 2023 DeepSeek".
  - `mistral-small-latest`: an alias of `mistral-small-2603`, Mistral Small 4 (v26.03), Apache 2.0 ([model page](https://docs.mistral.ai/models/mistral-small-4-0-26-03)). Every older Small is deprecated or retired, with Mistral Small 4 as the replacement.
  - `ministral-{3b,8b,14b}-latest`: aliases of `ministral-*-2512`, Ministral 3, Apache 2.0 ([8B page](https://docs.mistral.ai/models/ministral-3-8b-25-12)). The 2410 models have their own names (`ministral-8b-2410`). Only fake calls carry these names in our records.
  - MIT and Apache 2.0 cover the weights. Neither puts terms on outputs.
- **Route.** We call Mistral directly, so there is no reseller. Z.ai's and DeepSeek's own platform terms do not apply: we never called their APIs.
- **Unclear or assumed.**
  - That the owner's Mistral account is under the Commercial Terms, not Mistral's consumer terms. API keys are a commercial product; the account type was not checked.
  - Which release `mistral-small-latest` served on 2026-11-09: the journals record only the requested name. Today the alias is Mistral Small 4. Mistral's deprecation table retires the last older Small (3.2, `mistral-small-2506`) on 2026-07-31, so on 2026-11-09 the alias can only have served Small 4. That is inferred from the table, not recorded.

#### TypeSafe Jev (`jev-1.14.0`)

- **Terms.** [Master Customer Agreement](https://typesafe.ai/legal/mca), last updated 2026-09-23; [Acceptable Use Policy](https://typesafe.ai/legal/acceptable-use-policy), last updated 2026-09-23; [docs legal index](https://docs.typesafe.ai/legal.md). The site's [Terms of Use](https://typesafe.ai/legal/terms), 2026-09-19, cover only the website. Read 2026-11-12.
- **What is in our records.** Jev's replies are numbers, not words, for example `{"answers":{"plan_broken":{"noul":0.18,…}},"model":"jev-1.14.0",…}`. The questions sent to it are ours.
- **Ownership (s.4.2).** "TypeSafe does not claim ownership of Input and TypeSafe disclaims ownership of Output. TypeSafe hereby assigns to Customer all of its right, title, and interest, if any, in the Output."
- **Sharing.** Nothing forbids publishing Output. AUP 1.4: do not "mislead others about whether content, including Output, was generated by AI".
- **Attribution.** None asked.
- **Training and redistribution (s.2.3(b)).** Customer will not "use the Services or any Output … to perform model distillation, train a model to imitate the output of the Services, or develop (or to facilitate the development of) a similar or competing product or service". This binds us, the customer. Publishing is not training. "Facilitate" is the open word: a public dataset of Jev's answers could help someone else distil Jev.
- **Unclear.**
  - s.14.1 lists "Customer's Fees and all pricing information" among TypeSafe's Confidential Information. The repository and records carry Jev's input price (`input_usd_per_m: 0.042`) and per-call `cost_usd`. TypeSafe's own home page discusses its prices publicly; that the published price equals ours was not checked.
  - It is assumed that the owner's key was bought through the console checkout, so this MCA governs, not a separate order.

#### GPT-6 Luna (`gpt-6-luna`), through the owner's proxy

- **Route.** `codex.carlid.dev` runs the owner's `codex-cursor-proxy`. Its source, inspected on 2026-09-05, forwards to an upstream Responses API. Which upstream and which OpenAI account it uses is **not recorded** in this repository. Two cases give different terms:
  - an OpenAI API key falls under the OpenAI Services Agreement;
  - a ChatGPT/Codex sign-in falls under the consumer Terms of Use.
- **Services Agreement**, [PDF](https://cdn.openai.com/osa/openai-services-agreement.pdf) "ONLINE v.010126", read 2026-11-12.
  - s.4.1: "Customer: (a) retains all ownership rights in Input; and (b) owns all Output. OpenAI hereby assigns to Customer all OpenAI's right, title, and interest, if any, in and to Output."
  - s.3.3(e): Customer will not, "except for a Permitted Exception, use Output to develop artificial intelligence models that compete with OpenAI's products and services".
  - No clause forbids publishing Output, and no attribution is asked.
- **Terms of Use** ([page](https://openai.com/policies/row-terms-of-use/)). The page refused automated reads (HTTP 403). The wording below is from search-result excerpts of it, not from a full read:
  - "you (a) retain your ownership rights in Input and (b) own the Output. We hereby assign to you all our right, title, and interest, if any, in and to Output."
  - Among the prohibited uses: "Automatically or programmatically extract data or Output", representing Output as human-generated, and using Output to develop competing models.
- **Unclear, for a human.** If the upstream is a ChatGPT subscription, our calls were programmatic access to Output through a consumer plan. The Terms of Use excerpt forbids that, whatever happens to the Output afterwards. Publishing would not breach anything further, but it would put that use on record. Luna has been withdrawn from our configs.

#### Claude Opus 5.5 (`claude-opus-5-5`), the gate-quality judges

- **Route and terms.** The judges were Claude Code subagents on a Claude Max plan. Claude Code's [legal page](https://code.claude.com/docs/en/legal-and-compliance) says the "[Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms) — for Free, Pro, Max, and Ultra users" apply.
  - [Consumer Terms PDF](https://assets.claude.com/43c13f51a6d9755341433f79cf63c966ed9200ea.pdf), Anthropic PBC, effective 2025-10-08. The page served to the Spark is the EEA version (Anthropic Ireland): same date, the same clauses in slightly different wording.
  - [Usage Policy](https://www.anthropic.com/legal/aup), effective 2026-11-12.
  - Read 2026-11-12.
- **What is in our records.** The judges' labels (`useful`/`marginal`/`wasted`, `better`/`same`, flaws) and their short reasons, in `gq1/analysis/judge/labels/`.
- **Ownership (s.4).** "Subject to your compliance with our Terms, we assign to you all of our right, title, and interest—if any—in Outputs."
- **Sharing.** Nothing forbids publishing Outputs. s.4 makes the user responsible for "sharing them with others". The Usage Policy forbids misleading people about "whether they are interacting with a human" and content falsely attributed. The card's AI labelling covers both.
- **Attribution.** None asked.
- **Training and redistribution (s.3, item 2).** You may not use the Services "To develop any products or services that compete with our Services, including to develop or train any artificial intelligence or machine learning algorithms or models or resell the Services". This binds the user. Publishing is not training. There is no clause on redistributing Outputs.
- **Route condition (s.3, item 7).** No automated access "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it". Claude Code is Anthropic's own product, which its docs permit on these plans for "ordinary, individual usage". Whether nine parallel judging subagents count as ordinary use is the owner's call; it bears on the subscription, not on publishing.

#### Summary

| Model | Publishing outputs | Condition |
| --- | --- | --- |
| GLM 5.3 Flash (Mistral) | allowed | label as AI-generated (Mistral s.3.2); MIT weights |
| DeepSeek V4.1 Flash 1017 (Mistral) | allowed | same; MIT weights |
| Mistral Small 4 (`mistral-small-latest`) | allowed | same; Apache 2.0 |
| Ministral 3 (`ministral-*-latest`) | allowed | same; Apache 2.0; only fake calls in records |
| Jev (TypeSafe) | allowed | label as AI-generated; we may not distil from it; its pricing is "Confidential Information" |
| Claude Opus 5.5 (Claude Code, Max) | allowed | label as AI-generated; we may not train competing models on it |
| GPT-6 Luna (owner's proxy) | allowed under either OpenAI terms | **depends on the upstream account**; a ChatGPT sign-in makes the calls themselves out of terms |

#### Decisions (2026-11-12, general coordinator; branch `store-gate-2`)

1. **Jev's pricing is scrubbed until the owner confirms.** Its price, every Jev per-call `cost_usd` and Jev's share of any total are removed from published records. Totals are recomputed without Jev, or dropped where Jev is mixed in and cannot be separated. Other models' costs are kept. This is decision `jev_pricing: exclude` and the scrubber rule above, applied to every unit. No published unit carried Jev calls: of the 62 published batches none has one; only `gq1` and the fake `glf2` do. The code repository is public and still carries Jev's price (`living/configs/rethink.json`, `judgments.json`: `input_usd_per_m`) and Jev-mixed costs (`docs/GATE_QUALITY.md`). This decision does not cover those.
2. **Card note.** The runs card asks readers not to train models on the Jev answers or the Claude judge labels, as the assets card does for the Kimodo takes.
3. **Gate.**
   - Now `verified` in `store_config.json`: `mistral-small-latest`, `ministral-*-latest` and `ministral-*-2512` (Ministral 3), `jev*` and `claude-opus-5-5`, each with the card note.
   - The older `ministral-*-2410` releases (Mistral Research License, not read) stay unverified, so the pattern is not a bare `ministral-*`.
4. **Luna is held.** `gpt-6-luna` stays unverified while the coordinator asks the owner which account the proxy uses.
   - Batches with Luna calls: `b2` (472 calls, variant `luna`) and `b3` (2 calls, overflow), in `~/dev/slop-trials/.local/living/trials` on the Spark. Neither is published.
   - `b1` has no Luna call. Its instances' `models.json` lists `luna` as an overflow profile that was never used. The gate counts calls, so `b1` now passes it. The coordinator should decide whether a config mention counts as carrying Luna.
   - `gq1` does not contain the string `gpt-6-luna`.
   - No other trial root on the Spark has Luna calls. Laptop sessions were not scanned.
5. **`gq1`** is prepared, not uploaded (below).

## Fetch and publish

- **Asset packs name no machine** (`store-no-machine`): the motion library's `MANIFEST.json` has no `machine` field, its paths and commit message ("motion library") carry no machine label or host name, and the assets card says the takes were made "on our own hardware". The self-test `AssetPacksNameNoMachine` packs and publishes (local backend) with `STORE_MACHINE` set and searches every file, path, the commit log and the card for the label, the host name, `spark`, `laptop` and `dev-box`.

**Machine names: the rule for both datasets** (general coordinator, 2026-11-12):
- Role labels (`spark`, `laptop`, `dev-box`, the three roles the project's docs name) are allowed where they say where a run happened: the runs dataset's `batches/<role>/…` and `sessions/<role>/…` paths, its manifests' `machine` field and its commit messages. They help readers compare runs; nothing already published moves.
- Real host names, IP addresses, user names and home paths are never allowed, in either dataset (the scrubber redacts them; the publish checks refuse them).
- The assets dataset carries no machine label at all (above).
- **`fetch motion-library`** copies `motion/raw/*.npz` from the assets repository into `.local/kimodo/outputs/library/`, the folder `gen_anim.sh` and `gen_person.sh` read. This replaces the `rsync` from the Spark in `spark.sh`.
  - Every take is checked against `motion/MANIFEST.json`'s sha256.
  - A take already there with the same content is kept.
  - A different one is replaced only with `--force`.
  - It refuses to write into a read-only folder such as `~/kimodo-test`.
- **`fetch batch NAME [--machine M] [--unpack]`** fetches `batches/<machine>/<NAME>/` into `.local/living/store/batches/NAME/`. It refuses when the name exists on several machines and no `--machine` is given. With `--unpack` it rebuilds the evidence layout.
- **`publish`** packs the unit into a temporary folder, refuses it while any file is held, and hands the folder to a backend.
  - Batches go to `runs:batches/<machine>/<name>`, sessions to `runs:sessions/<machine>/<name>`, and the motion library to `assets:motion`.
  - `--backend local` is a folder per repository (`backends.local.root`, default `~/store-local`), with a `.commits.jsonl` log. The tests use it, and it can serve as a machine-local mirror.
  - `--backend hf` creates the repository if needed and uploads with `upload_folder`, or in commits of 100 files when there are more. It fetches with `snapshot_download`.

### Publishing is gated

Publishing to Hugging Face needs both of these:

1. `--yes-publish` on the command line;
2. `"publish_enabled": true` in the **machine-local** config, `~/.config/slop-store/config.json`, together with `backends.hf.namespace`.

`load_config` refuses a repository config that sets `publish_enabled`, so no commit can switch publishing on. The gate is checked before any file is read and before `huggingface_hub` is imported.

The tests cover the gate:
- each of the three off combinations refuses, and the fake API records no call;
- the CLI refuses with a poisoned `huggingface_hub` module in place, which would fail if anything imported it;
- the shipped config is off.

## Not covered

- **Laptop and dev-box manifests.** Not run; the commands are above.
- **Tables for verify evidence and sessions.** Verify evidence is planned as one tarball per checkout and date, and `pack` does not build that yet. Sessions pack with the batch shapes (one "instance" per top-level folder); their tables have not been designed separately.
- **Parquet.** Not produced: `pyarrow` is not installed on the Spark.
- **The viewer.** Whether the Hub viewer previews these `.jsonl.gz` files is unchecked until a first upload.
- **Speed.** About 0.4 s per MB (`l9`: 45 s for the dry run, 39 s for the pack). Packing all 5.7 GB of batches would take about 35 minutes.
- **Media.** Images and video are not checked for drawn text; that is why `session_media` is a decision.
- **Owner lines.** Lines a model paraphrased, and lines no resident heard (no prompt quotes them), are not found.
