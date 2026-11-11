---
# DRAFT, not published (docs/STORE.md). The owner decides the licence and whether to publish.
pretty_name: Slop Art Online assets (DRAFT)
license: other          # DRAFT: motion takes made with NVIDIA Kimodo (outputs unowned by NVIDIA);
                        # our own generated models and board pages proposed MIT
license_name: mixed-see-card
tags:
- motion
- animation
- text-to-motion
- 3d
- game
- synthetic
- ai-generated
# No `configs`: the files are binary takes and media, not tables; the viewer is off for this repo.
---

# Slop Art Online assets (DRAFT)

> **Draft.** Nothing here is published. The owner decides before any upload.

Generated assets of [Slop Art Online](https://github.com/devteapot/slop-art-online), kept so that any
machine can rebuild the game's look without copying folders between disks.

## Contents

| Path | What | Made by |
| --- | --- | --- |
| `motion/raw/<clip>_s<seed>.npz` | Raw text-to-motion takes on the SOMA 77-joint skeleton: every take kept for the clip library | NVIDIA Kimodo-SOMA-RP-v1.2 on a DGX Spark, from the prompts, seeds and parameters in `living/tools/blender/clips.json` |
| `motion/MANIFEST.json` | sha256 and size of every take | `store.py` |
| `motion/cliplab/<clip>/` | Clip lab scores (`checks.json`), contact sheets, the variants tried | `living/tools/kimodo/cliplab.py` |
| `motion/handoffs/*.tar.gz` | Clip batches handed between machines, with sha256 | `cliplab.py --handoff` |
| `board/…` | Asset board photographs and pages: each generated family beside the version the owner accepted | `living/tools/board/board.py`, the game's own renderer |

`store.py fetch motion-library` writes `motion/raw/` into `.local/kimodo/outputs/library/`, the
folder `gen_anim.sh` and `gen_person.sh` read, and checks every sha256.

The takes are raw model output. The game retargets them onto its characters, removes travel, and
cuts loops; those steps are scripts in the code repository.

## Licences (DRAFT notes, not legal advice)

- **Kimodo takes.** The model is under the NVIDIA Open Model License. It states that "NVIDIA does
  not claim ownership to any outputs generated using the Models", that "An output is not a
  Derivative Model", and that the user is "responsible for outputs and their subsequent uses"
  (ss. 1.1, 2.4). Its redistribution terms (s.3) apply to the model, not to outputs. Use of the
  model must follow NVIDIA's Trustworthy AI terms (s.2.3). The model was trained on the proprietary
  Bones Rigplay dataset; the model card states no terms on outputs beyond the licence.
- **Text encoder.** Kimodo encodes prompts with Meta Llama 3 8B Instruct (through LLM2Vec), under
  the Meta Llama 3 Community License: "Built with Meta Llama 3". Its s.1.b.v forbids using
  "any output or results of the Llama Materials to improve any other large language model". These
  takes are motion, not text, but users should not train other language models on them.
- **Our models, textures and board pages** are made by our Blender scripts and the game's
  renderer: MIT, like the code. The VRoid sample characters used as look-dev controls are CC0 (each
  file's VRM metadata, checked 2026-11-11; `living/tools/blender/THIRD_PARTY.md`). They are not
  included here.

## Not included

Game-ready GLBs (`just living-game-assets` regenerates them in minutes), Blender caches, and
hand-made tarballs whose contents are already under `motion/raw` and `motion/handoffs`.
