---
pretty_name: Slop Art Online assets
license: mit
# The takes are binary (.npz), not tables: the dataset viewer is off for this repository.
viewer: false
tags:
- motion
- animation
- text-to-motion
- 3d
- game
- synthetic
- ai-generated
---

# Slop Art Online assets

Generated assets from a **research build** of [Slop Art Online](https://github.com/devteapot/slop-art-online),
which is not a finished game. They are kept here so that the game's look can be rebuilt from them
without copying folders between disks.

**The motion takes are AI-generated:** they are raw output of a text-to-motion model, generated
from our own text prompts.

**Built with Meta Llama 3.** The motion model encodes its text prompts with Meta Llama 3 8B Instruct.
**Please do not use these motion takes to train language models.**

Licensed by NVIDIA Corporation under the NVIDIA Open Model License.

## Contents

| Path | What | Made by |
| --- | --- | --- |
| `motion/raw/<clip>_s<seed>.npz` | Raw text-to-motion takes on the SOMA 77-joint skeleton: every take kept for the clip library (645 takes) | NVIDIA Kimodo-SOMA-RP-v1.2 on our own hardware, from the prompts, seeds and parameters in the code repository's [`living/tools/blender/clips.json`](https://github.com/devteapot/slop-art-online/blob/main/living/tools/blender/clips.json) |
| `motion/somaskel77_skeleton.json` | The SOMA 77-joint skeleton the takes are on (joint names, parents, rest offsets), which the game's retargeting reads | dumped from the SOMA body model ([NVlabs/SOMA-X](https://github.com/NVlabs/SOMA-X)) |
| `motion/MANIFEST.json` | sha256 and size of every file, and the counts | `living/tools/store.py` |

Each take's prompt is its entry's `prompt` in `clips.json`, under the entry's `name`. The file
name is `<name>_s<seed>.npz`; the entry's `pick` is the seed the game uses, and the other seeds
are candidates kept for comparison.

`python3 living/tools/store.py fetch motion-library` (in the code repository) writes the takes and
the skeleton into `.local/kimodo/outputs/library/`, the folder that `gen_anim.sh` and
`gen_person.sh` read, and checks every sha256.

The game turns these takes into clips with scripts in the code repository: it retargets them onto
its characters, removes travel and cuts loops.

## Changes

- **2026-11-12.** Added 19 takes made for the game's walking and running speeds (`walk_v26`,
  `walk_v30`, `walk_v34`, `run_v48`, `run_stop_v48`, and the backward, sideways and diagonal
  `*_v26` and `*_v48` sets) and the skeleton file.
  - **Replaced:** `walk_start_s6.npz` and `run_start_s2.npz` with takes regenerated from corrected
    entries (their end keyframe now sits on the path at the take's last frame). The earlier
    versions of those two files remain in this dataset's history.
  - **Manifest:** re-packed with the new counts and checksums.

## Reproducing a take

The prompt, seed and parameters of each library entry are in `clips.json`. `living/tools/kimodo/batch.py`
and `living/tools/kimodo/cliplab.py` run the model. The same prompt and seed on the same model and
GPU stack give a close take, but not a bit-identical one.

## Licences

- **The takes.** They are output of NVIDIA Kimodo-SOMA-RP-v1.2
  ([model card](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2)), released under the
  [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/).
  The model card says: "This model is ready for commercial use." The licence says:
  - "Models are commercially usable."
  - "NVIDIA does not claim ownership to any outputs generated using the Models or Derivative Models."
  - §1.1: "An output is not a Derivative Model."
  - §2.4: "NVIDIA claims no ownership rights in outputs. You are responsible for outputs and their
    subsequent uses."
  - Its redistribution terms (§3) apply to the model, not to outputs. The notice it asks for when
    the model itself is distributed is given above as a courtesy: "Licensed by NVIDIA Corporation
    under the NVIDIA Open Model License".
  - The model was trained on the proprietary Bones Rigplay dataset; the model card states no terms
    on outputs.
- **The text encoder.** It is Meta Llama 3 8B Instruct (through LLM2Vec), under the
  [Meta Llama 3 Community License](https://www.llama.com/llama3/license/). Built with Meta Llama 3.
  Its §1.b.v forbids using "any output or results of the Llama Materials to improve any other large
  language model". Hence the request above.
- **The skeleton file** (`motion/somaskel77_skeleton.json`) is data of the SOMA body model, under the
  [Apache License 2.0](https://github.com/NVlabs/SOMA-X/blob/main/LICENSE) (NVlabs/SOMA-X).
- **This repository's own files** (manifests, card): MIT, like the code.
- **Not included:** the VRoid sample characters the game uses as look-dev controls (CC0, per each
  file's VRM metadata).

## Not included

- game-ready GLBs (`just living-game-assets` regenerates them);
- Blender caches;
- hand-made tarballs whose contents are already under `motion/raw`.
