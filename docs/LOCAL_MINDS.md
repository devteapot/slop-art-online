# Local minds: small open models on the Spark (Track L)

Status: **survey and design only** (2026-11-12, branch `research-local-models`). Nothing was downloaded, nothing was loaded on the GPU and no paid call was made. Every latency below for a local model is an **estimate** built from published GB10 measurements (cited) and our own call sizes (measured from journals). The test plan in §6 is what would turn the estimates into measurements; it waits for the general coordinator.

The question: can small open models served on the Spark carry the fast layers, which want latency under a second at a cost near zero?
- the fast lane's re-plan between blows ([FAST_LANE](FAST_LANE.md));
- a movement-input layer (Track M, being researched);
- cheap animal brains (Track P).

Added by the general coordinator: the rethink gate's quality question ([MIND_RESEARCH_IDEAS](https://github.com/devteapot/slop-art-online/blob/research-ideas/docs/MIND_RESEARCH_IDEAS.md) #3, `origin/research-ideas`). §5 treats "fewer calls through the gate" and "cheaper calls on a local model" as two ways to cut cost, and designs one test that measures both against quality.

## Short answer

- **Sub-second only for short replies.** On GB10 one generated token costs about 12–18 ms on the best small models (MoE with 3–4B active, 4-bit). The fast lane's reply, a `combat` patch of about 250 tokens, therefore takes **4–5 s locally at batch 1**, against DeepSeek Flash's measured 2.0 s p50 and 3.9 s p90. Local is slower for patch-shaped replies, not faster.
- **Where local fits.** It fits replies of 1–40 tokens on prompts whose fixed prefix is cached:
  - a `switch` or `keep` reply, or a choice among prepared routines: about 0.6–1.1 s;
  - the rethink gate's yes/no judgment: about 0.2–0.4 s;
  - a movement or decision label (Track M): about 0.3–0.5 s.
  - Animal impulses (Track P, about 1,100 tokens in and 70 out) come to about 1.2 s, the same as the cloud.
- **Capacity is the hard limit, not money.** The GPU prefills about 4–6k tokens a second. A town of 63 thinkers on today's people prompts needs about 7k fresh prompt tokens a second even with caching (0.8 deliberations a minute each, about 8.5k uncached tokens a deliberation), so local cannot carry people's think and compile at town scale, let alone at the 216 gate. It can carry a judge, a chooser or animal impulses for tens to low hundreds of characters.
- **Quality is the open risk.** The Ministral 3 open weights (3B, 8B and 14B, the same models as Mistral's `ministral-*-2512` API) were judged acceptable 0–1 of 12 times on people's decisions and 5 of 12 on animal impulses ([MODEL_COST](MODEL_COST.md)). Newer small MoE models (Qwen3.6-35B-A3B, gpt-oss-20b, Gemma 4 26B-A4B) are untested on our prompts.

## 1. Headroom, measured read-only (2026-11-12)

### What runs on the machine

| Thing | State during the window | GPU memory | Notes |
|---|---|---:|---|
| ComfyUI (`comfyui.service`, `~/ComfyUI`, :8188) | idle, up 2 d 18 h | 170 MiB (the only CUDA process) | Last output 2026-08-22. Its models (Wan 2.2, LTX-2.5, Krea 2) would take tens of GB when a job loads them. |
| `labd` (`labd.service`, `--enable-gpu`, 127.0.0.1:4440) | running, no child process | none | Schedules action-model jobs; it may start GPU work at any time. Not inspected beyond `ps`/`ss`: hands off. |
| Kimodo clip jobs (`~/kimodo-locomotion-*`, venv in `~/kimodo-test`) | not running | none | From file times, it ran 2026-11-11 15–17 h and 21 h–00 h. Batches come in bursts of hours. |
| Trial stack (`slop-trials-stdb` 2.14.1, `slop-trials-neo4j`) | a trial batch (`fs1f`) and verify-core scenes running | none | SpacetimeDB 2.2 GB RSS; CPU only. |
| Reference worlds (`sao-living_spacetimedb_1`, `sao-living-neo4j-1`) | up | none | Untouched. |
| Agents | about 10 Claude Code sessions, `living-mind`, cargo builds | none | CPU and memory only. |

No LLM weights are on disk: the Hugging Face cache is 17 GB, mostly metadata and dataset refs. Disk: 243 GB free of 917 GB.

### Sampled for 30 minutes

The read-only sampler (`nvidia-smi` utilisation and power, `/proc/meminfo`, the load average and the compute-process list) ran every 10 s from 13:18:54 for 30 minutes. The log, the sampler and the journal-size scripts are in `~/slop-evidence/local-minds-20261112/` on the Spark.

179 samples, 13:18:54–13:48:49, during normal work: a trial batch, verify-core scenes, about ten agent sessions and cargo builds.

| Measure | min | p50 | p90 | max |
|---|---:|---:|---:|---:|
| GPU utilisation (%) | 0 | 0 | 0 | 0 |
| GPU power (W) | 11.1 | 11.8 | 12.6 | 12.8 |
| `MemAvailable` (GiB of 122.5) | **84.4** | 105.0 | 107.8 | 108.1 |
| `MemFree` (GiB) | 4.4 | 21.9 | 41.8 | 46.6 |
| page cache (GiB) | 57.8 | 74.8 | 86.9 | 89.0 |
| swap free (GiB of 16) | 13.8 | 13.9 | 13.9 | 14.3 |
| load average, 1 min (20 cores) | 2.5 | 11.7 | 33.9 | 59.6 |

- **The GPU was idle for the whole window.** Its only CUDA process was ComfyUI's idle 170 MiB.
- **Memory is the binding resource, through builds.** `MemAvailable` fell from about 105 to 84 GiB while builds ran (load 34–60).
- **One window is not a schedule.** Kimodo or a labd job would have shown up as GPU use; neither ran in these 30 minutes.

Notes on reading it:
- **GB10 has one memory pool.** `nvidia-smi` shows "Memory-Usage: Not Supported". A model server's weights and KV cache come out of the same 122.5 GiB the builds, SpacetimeDB, Neo4j and the page cache use. The figure to watch is `MemAvailable`, not GPU memory.
- **The rule "keep 40 GB free"** leaves about 65 GiB for a model server on a quiet reading, and about 44 GiB at the window's build peak (84 GiB available). A ComfyUI video model or a Kimodo batch arriving as well would take most of that. The budget in §6 is **≤ 30 GB** for the server, weights and KV together.

### What a model server would slow

| If a server took X GB and Y% of the GPU | Who slows | How (expected; measure in §6) |
|---|---|---|
| Memory: 20–30 GB resident | builds (each agent's cargo can peak at several GB; target dirs about 20 GB on disk), the page cache | Less page cache means more disk reads in builds. Below about 40 GB available, the kernel reclaims cache, and then swaps (15 GB of swap, 2.3 GB already used). |
| Memory bandwidth: decode saturates it | **SpacetimeDB ticks** (trial worlds, the battle-scale acceptance runs), Neo4j, rustc and linking | GB10's CPU and GPU share one LPDDR5x bus (273 GB/s). Decoding streams the active weights once per token, so a busy server takes a large share of the bandwidth. That is the main risk to the coming quiet window: **no model server during acceptance runs.** |
| GPU time: Y% | Kimodo, ComfyUI, labd jobs | No MIG ("MIG M. N/A"), so CUDA contexts time-slice. Two jobs on the GPU each run slower, with no isolation. |
| CPU: 1–2 cores for the server process | trials, builds | Small. vLLM's API server and tokeniser use about one core. llama.cpp with full GPU offload uses about one core. |

## 2. Survey (as of 2026-11-12)

### Candidate models

Rows not checked on the model card are marked "card not read". Small dense means 1–14B; small MoE means total weights under about 35B with 3–4B active, which decode like a 3–4B dense model.

| Model | Total / active | Released | Licence | 4-bit size (est.) | Notes |
|---|---|---|---|---:|---|
| **Qwen3.6-35B-A3B** | 35B / 3B | April 2026 (card) | Apache-2.0 | ~20 GB (NVFP4/AWQ, community); FP8 official ~36 GB | 262k context; thinking can be switched off. A forum reply claims "over 100 tok/s" on Spark (unverified). |
| **gpt-oss-20b** | 21B / 3.6B | Aug 2025 | Apache-2.0 | ~13 GB (MXFP4, official) | A reasoning model (harmony format; effort low/medium/high). The most measured model on Spark. |
| **Gemma 4 26B-A4B** | 25.2B / 3.8B | first Gemma 4 release, by Apr 2026; tech report Jul 2026 | Apache-2.0 | ~15–16 GB (NVFP4/Q4, community) | 256k context. MTP drafters were published; on Spark MTP took it from 30.3 to 54.9 tok/s. |
| Gemma 4 12B | 12B dense | Jun 2026 | card not read | ~8 GB (NVFP4, Unsloth) | Dense, so it decodes about 3× slower than an A3B MoE. |
| Gemma 4 E4B / E2B | 4.5B / 2.3B effective | Mar 2026 | card not read | ~3–5 GB | Smallest current Google models; in SiliconBench at BF16 it ran 16–20 tok/s at c=1. |
| Qwen3.5-9B / 4B | dense | Mar 2026 (secondary sources) | Apache-2.0 (secondary) | ~5 / 2.5 GB | No Qwen3.6/3.8 below 27B was found on the Qwen org page. |
| Ministral 3 3B / 8B / 14B (`-2512`) | dense | Dec 2025 | card not read | FP8 official 4 / 9 / 14 GB | **Already judged on our prompts** through Mistral's API: poor (see §3.3). |
| Qwen3.6-27B, Qwen3.8-27B, Gemma 4 31B | dense ~27–31B | 2026 | – | ~16–18 GB | Too slow to decode for this use (about 10 tok/s at 4-bit, by the Qwen3 32B and Gemma 3 27B rows below). |
| Phi-4 / Phi-5, Nemotron Nano, Llama | – | – | – | – | No small Llama newer than 3.2. Phi and Nemotron Nano could not be confirmed from the org pages. |

### Serving stacks on aarch64 with GB10

| Stack | On Spark | Batching and prefix cache | Constrained JSON | Fit |
|---|---|---|---|---|
| **vLLM** (`vllm/vllm-openai:cu130-nightly`; 0.26 measured) | Works; FlashInfer CUTLASS kernels needed for FP4. One report: 1.1 tok/s on the emulation fallback, 77 tok/s with them. First load 10–15 min (120B); about 25 s of JIT on the first request. | continuous batching; automatic prefix caching | `response_format` `json_object` / `json_schema` through xgrammar (default) | **First choice** for anything batched. Pin the image digest: nightly tags are "a compatibility track rather than a reproducible pin". |
| **SGLang** (`lmsysorg/sglang:spark`) | Works; EAGLE3 speculative decoding up to 2× on Llama 3.1 8B (LMSYS). With CUDA graphs on, matched vLLM in one forum report. | RadixAttention prefix cache; continuous batching | xgrammar; jump-forward decoding helps JSON | An alternative to vLLM; the strongest prefix cache for shared system prompts. |
| **llama.cpp** (`llama-server`) | Native aarch64 CUDA build; the most measured stack (gpt-oss-20b at 58–83 tok/s decode). | slots with `cache_prompt`; weak batching (SiliconBench: 30 tok/s at c=8 against vLLM's 137) | GBNF grammar, `json_schema` | **Batch-1 fallback**: predictable memory (weights plus a fixed context), simplest to stop. |
| **Ollama** | Packaged llama.cpp | no real batching (forum: 60 tok/s at 8 streams against vLLM's 289) | `format` with a JSON schema | Not for serving minds. |
| **TensorRT-LLM** | Supported by NVIDIA; little small-model data on Spark | in-flight batching | guided decoding (xgrammar) | Engine builds per model make it the costliest to try. Not first. |

**Constrained output.** xgrammar's JSON-schema mask costs under 40 µs a token ([XGrammar paper](https://arxiv.org/pdf/2411.15100)). The remaining cost is compiling the grammar, about 0.1–0.3 s per new schema, so schemas must be stable and cached; a schema per request adds to time-to-first-token ([vLLM forum](https://discuss.vllm.ai/t/as-of-july-2026-what-are-some-general-tips-in-improving-the-speed-of-guided-decoding-in-vllm/2845)). Format is guaranteed; meaning is not.
- For the fast lane, a schema can restrict `switch` to the character's own routine names as an enum, so it cannot name a routine the character does not have.
- That is a different schema per character. It would be cached per character and rebuilt only when the routines change.
- Today `llm.rs` sends only `{"type": "json_object"}` (`request_body`); a per-purpose schema would be a small `llm.rs` change (verify-llm).

### Published GB10 numbers used here

| Model, quantisation, stack | Prefill tok/s | Decode tok/s, 1 stream | Many streams | Source |
|---|---:|---:|---|---|
| gpt-oss-20b MXFP4, llama.cpp | 3,611 (pp2048); 4,506 empty, 2,689 at 32k | 80 (tg32); 83 empty, 62 at 32k | – | JetsonHacks (via search, page since gone), [VerdictBits](https://verdictbits.com/reviews/dgx-spark-benchmarks/) |
| gpt-oss-20b MXFP4, Ollama 0.12.6 | 3,224 | 58.3 | – | [Ollama](https://registry.ollama.ai/blog/nvidia-spark-performance) |
| Qwen3-30B-A3B 4-bit, vLLM 0.26 / Ollama | – | 77.1 / 85.2 | 313 total at 8 (vLLM) | [NVIDIA forum](https://forums.developer.nvidia.com/t/measured-inference-benchmarks-on-a-single-dgx-spark-same-harness-across-ollama-llama-cpp-and-vllm-notes-data-published/379766) |
| Gemma-4-26B-A4B NVFP4 + MTP, vLLM | – | 54.9 (30.3 without MTP); TTFT 94 ms (short prompt) | 304 total at 8 | same forum post |
| unnamed model, vLLM | "~6,000 flat out to 27k tokens"; 27k prompt in 3.6 s | ~56 | – | same forum post |
| Llama 3.1 8B FP8, SGLang | 7,991 | 20.5 | 368 total at 32 (11.5 a stream) | [LMSYS](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark) |
| Llama 3.1 8B q4_K_M / q8_0, Ollama | 7,614 / 6,110 | 38.0 / 25.2 | – | Ollama |
| Gemma 3 12B q4_K_M, Ollama | 1,894 | 24.3 | – | Ollama |
| Qwen3 32B q4_K_M, Ollama | 705 | 9.4 | – | Ollama |
| Gemma-4-E4B BF16, vLLM | – | 17.2 | 137 total at 8, 239 at 16 | [SiliconBench](https://arxiv.org/abs/2609.19169) (tables read through an extraction) |
| Nemotron-3-Super-120B-A12B NVFP4, vLLM (out of range) | 1,636–1,884 | 23 | vLLM advises `--max-num-seqs 4`: above four decode streams "time-to-first-token spikes" | [vLLM blog](https://vllm.ai/blog/2026-06-01-vllm-dgx-spark) |

Decode on GB10 is bound by memory bandwidth (273 GB/s), so the active weights set the speed:
- 3–4B active at 4 bits: about 55–85 tok/s;
- dense 8B at FP8: about 20–25 tok/s;
- dense 12B at 4 bits: about 24 tok/s.

Speculative decoding (MTP, EAGLE3) gives 1.5–2× on top. Prefill is bound by compute: about 4,000–8,000 tok/s on these models, falling with depth.

## 3. Our call shapes

### 3.1 Measured sizes (from journals; the `prompt_tokens`/`completion_tokens` fields)

DeepSeek V4.1 Flash (thinking off or `low`) and GLM 5.3 Flash (`low`). Error rows are excluded; latency is the call's total.

| Call | Where | n | Prompt p50 / p90 | Cached p50 | Out p50 / p90 (reasoning p50) | Visible out p50 | Latency p50 / p90 |
|---|---|---:|---:|---:|---:|---:|---:|
| think, DeepSeek | r2b–r2d (arena) | 84 | 4,639 / 5,060 | 2,688 | 445 / 780 (206–254) | 250 | 2.0 / 3.9 s |
| think, DeepSeek | ar2, bi1 (all minds) | 459 / 1,706 | 5,655–6,403 / 6,220–7,032 | 2,560–2,688 | 469–490 / 739–889 (210–232) | – | 2.1–2.2 / 4.5 s |
| think, GLM | ar2, bi1 | 1,318 / 4,752 | 5,568–6,138 | 1,152 | 293–301 (47–53) | – | 6.6–6.9 / 12.9–13.8 s |
| deliberate (compile), DeepSeek | ar2, bi1 | 1,619 / 1,669 | 14,591–15,320 / 15,140–15,972 | 9,856–9,984 | 1,045–1,116 (760–810) | 244 (r2d) | 3.7–3.8 / 8.0–8.4 s |
| talk, DeepSeek | ar2, bi1 | 927 / 2,283 | 1,938–2,282 | 896–1,024 | 102–106 (0) | 102–106 | **0.67 / 1.7–1.9 s** |
| consolidate, DeepSeek | ar2, bi1 | 625 / 1,660 | 5,402–7,451 | 3,200–3,328 | 851–898 (0) | – | 2.7 / 5.0–5.6 s |
| fast (as built), from the fast prompt's text | verify-minds `fast-lane` (fake model, 9 requests) | 9 | about 12,500–12,600 (39,948 chars of system prefix ≈ 11,100 tokens, plus 1,300–5,300 chars of user text ≈ 400–1,500) | – | – (fake reply) | – | – |
| animal think (impulse) | MODEL_COST samples (Mistral Small 4 era) | 24 a config | 1,018–1,137 | – | 42–96 | – | GLM 1.9 / 5.2 s, DeepSeek 1.4 / 6.0 s |
| animal compile | same | 24 | 3,341–3,519 | – | 144–708 | – | GLM 3.0 / 16.6 s, DeepSeek 1.6 / 4.4 s |
| rethink gate (cheap-LLM arm) | MIND_HARNESS §6 replay | 650 | about 910 (Jev: 1,420) | – | about 43 | – | GLM 1.4 / 4.0 s; Jev 135 / 171 ms |

Notes:
- **No real fast-lane reply exists yet.** The fast lane was merged with fake models only (r2ef journaled no `fast` call; the 9 verify-minds prompts carry fake replies). Its prompt is in **compile's size class (about 12.5k tokens), not think's**. FAST_LANE.md §4's "2,000 fresh and 4,000 cached" undercounts the fixed prefix: `world_rules()` plus `grammar()` is about 11k tokens. Since the prefix is fixed, it caches. The reply's size is estimated from think's and compile's visible output: about 250 tokens for a `patch` or `routine`, and 25–40 for `switch` or `keep`.
- Character-to-token ratio on DeepSeek's tokenizer, from r2d: 3.6–3.7 characters a prompt token, 2.9–3.5 a reply token. Qwen and Gemma tokenizers are similar to within about 10–15%.
- **What cloud speed implies.** DeepSeek's talk calls return about 100 tokens in 0.67 s, a decode rate of about 150–250 tok/s, three times the best small model on GB10. Cloud TTFT on DeepSeek was 0.5–0.6 s in MODEL_COST.

### 3.2 Estimated local latency per call shape

Assumptions:
- **Model class:** 3–4B active MoE at 4 bits (Qwen3.6-35B-A3B, gpt-oss-20b at low effort, or Gemma 4 26B-A4B with MTP) on vLLM or SGLang.
- **Speeds:** prefill 4,000–6,000 tok/s; decode 60–70 tok/s for one stream at these depths, and about 37 a stream at 8 streams (313 tok/s in total). At 32 streams, about 10–15 a stream, from the 8B row.
- **Prefix caching:** the cached system prefix is reused across characters (vLLM APC / SGLang radix), so "fresh" means the per-call tail.
- A dense 8–9B model at FP8 is about 3× slower to decode; a dense 4B at FP8 or NVFP4 about 1–1.5× slower (estimated from bandwidth: not measured).

| Shape | Fresh prompt | Out | Batch 1: TTFT / total | Batch 8 (arrivals together): worst TTFT / total | Batch 32 | Cloud today (p50 / p90) |
|---|---:|---:|---|---|---|---|
| **Fast lane, `patch`** | 1.5–2k (11k cached); 12.5k uncached | 250 (p90 370) | 0.35–0.6 s / **4.3–4.8 s** (p90 ~6.5 s); uncached 2.5–3.5 / 6.5–7.5 s. With MTP: about 3 s | 2.5–4 s / 9–11 s | not viable (17–25 s decode) | DeepSeek 2.0 / 3.9 s (think-sized estimate) |
| **Fast lane, `switch`/`keep`** only | same | 25–40 | 0.35–0.6 / **0.8–1.2 s** | 2.5–4 / 3.5–5 s | prefill-bound: 8–12 s | same call |
| Choice among prepared routines (COMBAT_MIND §3.5; Track M decision) | 200–1,000 (per-character prefix cached) | 3–10 | 0.05–0.25 / **0.15–0.45 s** | 0.4–2 / 0.6–2.3 s | 1.6–8 s | Jev 135 / 171 ms + delivery |
| Rethink gate judge (cheap-LLM arm) | 900–1,400 | 1–40 (1 with logprobs) | 0.15–0.35 / **0.2–0.9 s** | 1.2–2.8 / 1.5–3.8 s | 5–11 s | Jev 135 / 171 ms; GLM 1.4 / 4.0 s |
| Animal impulse (Track P) | 1,000–1,140 (little shared prefix) | 40–100 (GLM ~96) | 0.2–0.3 / **0.9–1.7 s** | 1.5–2.3 / 3–5 s | 6–9 s | GLM 1.9 / 5.2 s; DeepSeek 1.4 / 6.0 s |
| Animal compile | 3,400 | 150–700 | 0.6–0.9 / 3–11 s | 4–7 / 9–25 s | – | GLM 3.0 / 16.6 s; DeepSeek 1.6 / 4.4 s |
| Talk | 1,900–2,300 | ~105 | 0.35–0.6 / 1.9–2.3 s | 3–5 / 6–8 s | – | DeepSeek **0.67 / 1.8 s** |
| Person think | 3–4k fresh (2.6k cached) | 270–500 | 0.6–1 / 5–9 s | – | – | DeepSeek 2.1 / 4.5 s |

**Capacity ceiling** (the GPU's whole prefill and decode budget):
- Prefill: about 4–6k fresh tokens a second. Decode: about 300 tokens a second in total at 8 streams, roughly 400–500 at 16–32 (by the 8B and E4B rows).
- Gate judge: about 4 calls a second at 1,100 fresh tokens. The gated live run had **49 gate calls per thinker an hour**, so local could judge for about **250–300 thinkers**.
- Routine choice: about 6–20 calls a second (200–1,000 fresh tokens). At 1 Hz that is 6–20 characters; at once every 10 s, 60–200. **Track M at several Hz per character does not fit** beyond a handful of bodies; a movement layer that needs that rate belongs in the graph or in code, not in a model.
- Animal impulses: about 4–5 calls a second, prefill- and decode-bound together.
- People's think plus compile: each deliberation needs about 8.5k fresh tokens (think 6k with 2.6k cached, compile 15k with 9.9k cached) and about 750 generated. That is about 0.4–0.7 deliberations a second, **about 30–50 on-stage thinkers at the measured 0.8 per minute**, if nothing else runs on the GPU and each waits 10–25 s. Out of the question at the 216 gate.

### 3.3 Quality risk for JSON graph patches

What is already measured on our prompts (MODEL_COST, blind judges, 2026-11-09), for the Ministral 3 open weights through Mistral's API:

| Task | Ministral 3B / 8B / 14B judged acceptable | Reference |
|---|---|---|
| person think | 0 / 1 / 1 of 12 | GLM `low` 12/12 |
| person compile | 1 / 0 / 2 of 6; graph warnings 0.64–1.61 a graph for animal compiles, against 0.05 | GLM `low` 2/6, DeepSeek 3/6 |
| talk | 0 / 1 / 3 of 12 | DeepSeek 12/12 |
| animal impulse | 5 / 5 / 5 of 12 | GLM 12/12 |
| animal memory | 0 / 0 / 0 of 8 | GLM `high` 8/8 |

The failure kinds the judges named are the ones a `combat` patch can carry:
- invented acts, skills or targets (phantom ids);
- the prompt's example copied (the `strike` against `attack` mistake that r2c showed even in large models);
- unconditional branches that block the rest of the graph;
- added decisions the prompt did not ask for;
- human motives in animals.

For newer models:
- **Long fixed prompts.** The fast and compile prompts carry an 11k-token grammar. Small models follow long instructions less well than short ones, and the grammar is where the rules of the graph live.
- **Constrained decoding** removes syntax failures: `json_object` failures are already rare, about 0–4% "usable" misses for every model. It also makes `switch` names valid by construction. It does not stop a valid graph that does the wrong thing.
- **Reasoning models** (gpt-oss, Qwen thinking) must run at low effort or with thinking off. Every hidden token costs 12–18 ms locally, against about 4–6 ms in the cloud.
- **None of Qwen3.6-35B-A3B, gpt-oss-20b or Gemma 4 26B-A4B has been judged on our prompts.** The size class's record above is the prior: expect animal impulses and short choices to be closer to acceptable than graph writing.

## 4. Against the cloud

| Call | Cloud model: p50 / p90 latency, $ a call | Best local estimate: p50 latency | Local wins? |
|---|---|---|---|
| fast `patch` | DeepSeek: about 2.0 / 3.9 s (think-sized; fast-sized not yet measured), about $0.0013 (bound; FAST_LANE §4). With the full 12.5k-token prompt, mostly cached: $0.0006–0.0013. | 4.3–4.8 s (3 s with MTP) | **No** on latency; yes on money |
| fast `switch`/`keep` | the same call | 0.8–1.2 s | Yes, if the reply is restricted to these kinds |
| routine choice | Jev 135–174 ms p50, 166–240 ms p95, $0.00006 a question | 0.15–0.45 s | Close; Jev faster. Local is free and never rate-limited. |
| rethink gate | Jev $0.00006 a question; GLM `low` 1.4 / 4.0 s, $0.00016 | 0.2–0.9 s | Yes against GLM; equal against Jev on price, slower than Jev |
| animal impulse | GLM `low` 1.9 / 5.2 s, €0.17 a 1k calls (about $0.0002) | 0.9–1.7 s | Slightly on latency; the money saved is small |
| talk | DeepSeek 0.67 / 1.8 s, about $0.0005 | 1.9–2.3 s | **No** |
| person think, compile | DeepSeek 2.1 / 4.5 s and 3.7 / 8.0 s; GLM 6.6 / 13 s | 5–9 s, 10–25 s | No, and capacity runs out |

**In money:**
- **Fast lane at its global cap** (2 calls a second): $0.0026 a second, **about $9.40 an hour** on DeepSeek.
- **Local power:** about 0.1 kWh an hour (estimate: +60–100 W at load).
- **The local price is not money.** It is the GPU's time, which Kimodo, ComfyUI and labd also want, the memory, and the bandwidth the authority shares (§1).
- **The quality, unmeasured, is the real cost.**

## 5. Two ways to cut cost: the gate and a local model (with idea #3)

### The two levers

Both act on the same stream of non-urgent deliberations (think plus compile; about 0.8 a minute per person on stage):

| Lever | What it removes | Measured so far | Quality cost |
|---|---|---|---|
| **Gate** (`LIVING_RETHINK=jev`, built, off) | whole deliberations: fewer calls | Replay: 42% of 650 non-urgent deliberations judged wasted, 16% harmful to skip. Live: −37% to −50% deliberations, −24% to −40% cost. Lone newcomer among instinct residents only. | The **harmful holds**: Jev at 0.3 held 46%, catching 62% of waste and 19% of harmful-to-skip. Never measured where every resident thinks. |
| **Local model** | the price of each call that runs | none | **Each call that runs is worse.** Unmeasured on our prompts for current models; the Ministral record is the prior. |

### How they combine

- **Cost multiplies.** For N triggers, a hold rate h, a deliberation price c_d and a gate price c_g a question, the cost is N × [(1 − h) × c_d + c_g]. A local model sets c_d to about zero in money and a local judge sets c_g to about zero, so the two cuts stack. In money, local alone beats the gate alone; capacity (§3.2) stops local from carrying people's deliberations at town scale, and the gate is what brings the load down toward what the GPU can carry.
- **Quality does not add independently.**
  - The gate holds mostly restated plans. The deliberations it passes are enriched for the useful ones: broken plans and new events. Those are where a small model's deficit hurts most.
  - So **a local model's quality must be scored on the gate's survivors**, not on all triggers. Scoring it on all triggers flatters it.
  - Conversely, a gate's holds cost less when the alternative to holding is a cheap local think rather than a cloud one.
- **A third route the combination opens: tiering instead of holding.**
  - The gate's verdict can choose the model rather than only think or hold: a clear yes goes to the cloud, the uncertain band to the local model, a clear no is held.
  - Jev at 0.3 holds 19% of harmful-to-skip deliberations. Some of those would be answered, imperfectly but for free, instead of skipped.
  - This is a mind-service routing change (a mix keyed by the gate's p), not a world law. Like the gate, it must never touch urgent reasons, a player's acts or the first thought.
- **The judge itself is the best local job:** one-token answers, short prompts, a capacity of hundreds of thinkers (§3.2), so c_g goes to zero.

### One test: quality against cost, on the same requests

**The request set.** Non-urgent deliberation points, each with what the cloud actually produced:
- MIND_HARNESS §6's 650 points (b1, w1, w2), which already have blind labels: `useful`, `marginal`, `wasted`, harmful to skip. On the dev-box: `.local/living/rethink/`.
- New all-minds evidence on the Spark, per idea #3:
  - bi1: 6 runs, 1,706 DeepSeek and 4,752 GLM think calls;
  - ar2: 30 runs;
  - st2b: in `~/slop-trials2b/.local/living/trials/st2b`.
  - Sample about 300 points from these, stratified by reason kind: quiet moment, plan finished, feeling, first sight, cue. Each keeps its exact journaled think and compile messages and replies.

**For every point, four things are produced. None needs a paid call except the gate's Jev arm and the cloud baseline.**
1. **Gate verdicts:** Jev at 0.3 (pennies), GLM at 0.7 (about $0.05 for 300), and a **local judge**: the same cheap-LLM arm with `rethink.json` `llm.route` set to a local profile. `rethink-replay --arm llm` already takes the route from config.
2. **A local deliberation on the same prompt.**
   - The recorded think messages go, byte for byte, to each local candidate.
   - The compile step is run two ways: given the cloud's think (the compiler alone) and given the local think (end to end).
3. **A cloud baseline of the cloud against itself.** The same model answers a 60-point subset again (about $0.25 on DeepSeek), because fresh inference is not deterministic; agreement with the cloud means little without it.
4. **Mechanical checks:**
   - the JSON parses;
   - the graph passes `living_rules::graph::from_value_lenient` with no new warnings;
   - every skill and routine named exists;
   - every target id is in the scene (no phantom);
   - no invented act.

**The judge.** Blind and two-part, in the scheme §6 already used (two fresh judges, each with half the points; the models and gate verdicts are hidden):
- **(a) Value:** was the cloud deliberation useful, marginal or wasted, and would skipping it have hurt? Labels exist for the 650; new ones for the about 300.
- **(b) Pairwise:** local reply against cloud reply, in random order: better, same or worse. Also: "worse in a way that would hurt the character": a wrong target, a broken plan kept, a phantom, an invented act.

**The arms**, scored offline on the same points:

| | cloud deliberation | local deliberation | local think + cloud compile | tiered by the gate's p |
|---|---|---|---|---|
| no gate | today | | | – |
| Jev 0.3 | | | | |
| GLM 0.7 | | | | |
| local judge | | | | |

For each cell:
- **Cost a resident-hour** = Σ over passed points of the call's token price, plus the gate's price, scaled by the trigger rate. Local calls are $0, and their GPU-seconds are reported beside.
- **Harm rate** = (held and harmful to skip + passed, local and harmful-worse) / points, weighted back to the population as §6 did.
- **Also reported:** waste caught, phantom and invalid rates, and latency (p50 and p90 at the evidence's own arrival times, replayed).

Result: a cost-against-harm frontier.
- **Pass reading:** a cell is better than today if its harm is within the cloud-against-cloud spread and its cost is lower by more than that spread.
- **A batch holds one model mix across its arms and records it** (idea #3's interaction note); every trial batch states which mind and rules switches were on.

**Live check, afterwards and paid.** Idea #3's hamlet and Cullet runs (about $16) are the live test for the gate arms. Add one local arm, the best cell of the frontier, only if the GPU budget of §6 allows it during that window. The measures are idea #3's: deliberations and dollars a resident-hour, the time from a failed act to a changed plan, the talk guards and `plans_other`.

## 6. Test plan (waits for the general coordinator; free in money)

### Phase 0: no GPU, no download

- **Build the replay set** (above) as JSONL: the exact messages, the cloud reply, the purpose and the arrival time.
- **Get MODEL_COST's samples.** Its `samples.jsonl`, with judged animal and person items, is not on the Spark (git-ignored, on the machine that ran it). Copy it in.
- **A replay tool** (`living/tools/local_replay.py`):
  - sends each request to an OpenAI-compatible URL at a set concurrency, or at the recorded arrival times;
  - records the journal's fields (`latency_ms`, `prompt_tokens`, `completion_tokens`, `cached_tokens`) plus the time to first token, from streaming;
  - is tried first against `fake_llm.py`.
- **A local profile in a scratch `models.json`:**
  - `base_url` `http://127.0.0.1:<port>/v1`, `json_mode` true;
  - `reasoning_effort` null for every purpose, `prompt_cache_key` false;
  - `key_env` pointing at a dummy variable.
  - No `llm.rs` change is needed to try it. The per-purpose `json_schema` is a later `llm.rs` change, verified with verify-llm.

### Phase 1: downloads (about 50 GB of disk; 243 GB free)

| Candidate | Why | Weights | Download (est.) |
|---|---|---:|---|
| **Qwen3.6-35B-A3B**, 4-bit (NVFP4 or AWQ) | strongest current small MoE on paper; thinking can be switched off | ~20 GB | 10–30 min |
| **gpt-oss-20b**, MXFP4 (official) | best-measured on Spark; smallest of the MoEs | ~13 GB | 5–15 min |
| **Gemma 4 26B-A4B**, NVFP4, + MTP drafter | MTP measured on Spark (+81%) | ~16 GB | 10–20 min |
| (control) Qwen3.5-9B or Gemma 4 E4B, FP8 | a dense small model for the judge and the impulses | 5–10 GB | 5 min |

Into a dedicated directory such as `~/local-minds/models`, not ComfyUI's tree nor `~/.cache/huggingface`. Each download goes into its own new directory, and nothing from it is run except by the serving stack. One model is loaded at a time.

### Phase 2: serve beside the existing work without disturbing it

- **One container**, image pinned by digest (`vllm/vllm-openai:cu130-nightly@sha256:…`; llama.cpp as the fallback), bound to `127.0.0.1` only, named `local-minds`.
  - Limits: `--memory 32g --memory-swap 32g --cpus 4`.
  - vLLM: `--gpu-memory-utilization 0.22` (≈ 27 GB of 122.5; **never the default 0.9**, which would take the machine's whole pool), `--max-num-seqs 8`, `--max-model-len 16384`, `--enable-prefix-caching`.
- **When:**
  - only while `nvidia-smi --query-compute-apps` shows no process but ComfyUI's idle 170 MiB, and `MemAvailable` is above 70 GB before the load;
  - never during the battle-scale acceptance window, Kimodo batches or labd GPU jobs;
  - announced to the coordinator before each session.
- **Watchdog**, every 5 s while the container runs:
  - if `MemAvailable` falls below 45 GB, another CUDA process appears, or the session passes its time box, it runs `docker stop local-minds` (graceful, 30 s; then the container is removed);
  - it logs why.
- **Shut down:** `docker stop` and `docker rm`. Check that `MemAvailable` returns within about 1 GB of the pre-load reading and that no process is left on the GPU. Weights stay on disk until the coordinator says otherwise.
- **The cost to others, measured, not assumed.** Run SpacetimeDB tick timing (`bench.py`, a scratch verify-core world, the stamina battle scene) with the server idle, with it decoding at batch 1, and at batch 8. That gives the authority's tick p50, p95 and p99 under the shared memory bus. Also time one `just living-check` with and without the server.

### Phase 3: measurements, per candidate (time-boxed)

1. **Load and warm-up:** 10–20 min, including JIT; the first request's time is recorded.
2. **Synthetic sweep:** 20 min.
   - Prompt sizes 1k, 4k and 13k (with the fast prompt's real 11k-token prefix, cached and uncached).
   - Outputs of 5, 40 and 250 tokens.
   - Concurrency 1, 4, 8 and 32.
   - Measures: time to first token, total, decode per stream, and memory.
3. **Replay:** 30–40 min.
   - Requests: the 9 fast prompts; 100 think, 50 compile and 50 talk calls from r2b–r2d and ar2/bi1; the 24 MODEL_COST animal items; 300 gate states; 300 deliberation points.
   - Measures: latency, and the share valid and usable on the first try.
4. **For the fast lane specifically:**
   - The replies' kinds (keep, switch, patch, routine) against the cloud's on the same prompts.
   - Since no cloud fast replies exist, the reference is the first paid fast-lane arm (FAST_LANE §6, about $0.40, already planned), or a one-off cloud pass over the fake run's recorded fast prompts (about 50 × $0.0013 ≈ $0.07). Either needs authorisation.
   - The cloud baseline against itself, as in §5.
5. **Judging**, after all candidates: §5's two-part blind judge. With fresh Claude subagents as before, about 1,000 items. With a paid judge model, about $3–6.

**GPU time:** about 1.5 h a candidate, so **4–6 GPU-hours** over two or three sessions, at most 30 GB of memory. Batch 32 is run only in the sweep, for at most 5 minutes.

### Risks

- **Bandwidth contention** slows the authority's ticks and builds while the server decodes. It is measured in phase 2; the server is off during acceptance runs.
- **Memory:** a wrong `--gpu-memory-utilization` takes most of the pool. Mitigated by the cgroup limit, the explicit fraction and the watchdog.
- **Stack immaturity on GB10:**
  - nightly images and FP4 kernels (emulation fallbacks of about 1 tok/s are reported);
  - first loads of 10–15 minutes;
  - llama.cpp is the fallback.
- **Quality:** the prior (Ministral) is poor. If no candidate's harm rate falls within the cloud's own spread on deliberations, local stays limited to judges and choices.
- **Comparability:** a batch mixing local and cloud models across arms is not comparable. Each arm records its mix.
- **Not a scale result:** none of this establishes performance at the 216 gate or the contract's targets. Model inference is reported separately, as the performance contract asks.

## Sources

- GB10 measurements:
  - [NVIDIA forum: one harness across Ollama, llama.cpp and vLLM](https://forums.developer.nvidia.com/t/measured-inference-benchmarks-on-a-single-dgx-spark-same-harness-across-ollama-llama-cpp-and-vllm-notes-data-published/379766)
  - [LMSYS: SGLang on DGX Spark](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark)
  - [vLLM on DGX Spark](https://vllm.ai/blog/2026-06-01-vllm-dgx-spark)
  - [Ollama on DGX Spark](https://registry.ollama.ai/blog/nvidia-spark-performance)
  - [VerdictBits DGX Spark benchmarks](https://verdictbits.com/reviews/dgx-spark-benchmarks/)
  - [SiliconBench](https://arxiv.org/abs/2609.19169)
  - [ai-muninn: Qwen3.8-Flash-Next NVFP4 on Spark](https://ai-muninn.com/en/blog/qwen38-flash-next-nvfp4-dgx-spark-vllm-recipe)
  - [Spark Arena leaderboard](https://sparkarena-readme.static.hf.space/README.md)
- Models:
  - [Qwen on Hugging Face](https://huggingface.co/Qwen) and [Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
  - [Google](https://huggingface.co/google) and [gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it); [Gemma 4 on vLLM](https://vllm.ai/blog/gemma4)
  - [Ministral 3 collection](https://huggingface.co/collections/mistralai/ministral-3)
  - [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b)
  - [Meta Llama](https://huggingface.co/meta-llama), [Microsoft](https://huggingface.co/microsoft)
- Structured output:
  - [XGrammar](https://arxiv.org/pdf/2411.15100) and [XGrammar-2](https://blog.mlc.ai/2026/05/04/xgrammar-2-fast-customizable-structured-generation)
  - [vLLM forum on guided-decoding speed](https://discuss.vllm.ai/t/as-of-july-2026-what-are-some-general-tips-in-improving-the-speed-of-guided-decoding-in-vllm/2845)
- Project evidence:
  - journals under `~/dev/slop-cm-r2{b,c,d}`, `~/dev/slop-runs-arrive/.local/living/trials/{ar2,bi1}` and `~/dev/slop-cm-fos`/`slop-cm-fl` (verify-minds `fast-lane`);
  - [MODEL_COST](MODEL_COST.md), [MIND_HARNESS §6](MIND_HARNESS.md#6-rethink-gate), [FAST_LANE](FAST_LANE.md), [COMBAT_MIND](COMBAT_MIND.md).

SpacetimeDB: this design changes no table, reducer, view or subscription. A local model is another OpenAI-compatible endpoint behind the mind service, outside reducers, as AGENTS.md requires. No SpacetimeDB documentation was needed for it, and none was consulted.
