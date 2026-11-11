---
pretty_name: Slop Art Online assets
license: mit
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
which is not a finished game. They are kept here so that any machine can rebuild the game's look
without copying folders between disks.

**The motion takes are AI-generated:** they are raw output of a text-to-motion model.

**Built with Meta Llama 3.** The motion model encodes its text prompts with Meta Llama 3 8B Instruct.
**Please do not use these motion takes to train language models.**

## Contents

| Path | What | Made by |
| --- | --- | --- |
| `motion/raw/<clip>_s<seed>.npz` | Raw text-to-motion takes on the SOMA 77-joint skeleton: every take kept for the clip library | NVIDIA Kimodo-SOMA-RP-v1.2 on a DGX Spark, from the prompts, seeds and parameters in the code repository's `living/tools/blender/clips.json` |
| `motion/MANIFEST.json` | sha256 and size of every take | `living/tools/store.py` |

`python3 living/tools/store.py fetch motion-library` (in the code repository) writes `motion/raw/`
into `.local/kimodo/outputs/library/`, the folder that `gen_anim.sh` and `gen_person.sh` read, and
checks every sha256.

The game turns these takes into clips with scripts in the code repository: it retargets them onto
its characters, removes travel and cuts loops.

## Reproducing a take

The prompt, seed and parameters of each library entry are in `clips.json`. `living/tools/kimodo/spark.sh`
and `living/tools/kimodo/cliplab.py` run the model. The same prompt and seed on the same model and
GPU stack give a close take, but not a bit-identical one.

## Licences

- **The takes.** They are output of NVIDIA Kimodo-SOMA-RP-v1.2, under the
  [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/):
  - "NVIDIA does not claim ownership to any outputs generated using the Models";
  - "An output is not a Derivative Model";
  - the user is "responsible for outputs and their subsequent uses" (ss. 1.1, 2.4);
  - its redistribution terms (s.3) apply to the model, not to outputs;
  - the model was trained on the proprietary Bones Rigplay dataset; the
    [model card](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2) states no terms on outputs.
- **The text encoder.** It is Meta Llama 3 8B Instruct (through LLM2Vec), under the Meta Llama 3
  Community License. Built with Meta Llama 3. Its s.1.b.v forbids using "any output or results of
  the Llama Materials to improve any other large language model". Hence the request above.
- **This repository's own files** (manifests, card): MIT, like the code.
- **Not included:** the VRoid sample characters the game uses as look-dev controls (CC0, per each
  file's VRM metadata).

## Not included

- game-ready GLBs (`just living-game-assets` regenerates them);
- Blender caches;
- hand-made tarballs whose contents are already under `motion/raw`.
