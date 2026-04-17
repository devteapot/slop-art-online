# HY-World 2.0 — Integration Assessment for slop-art-online

> **Date:** 2026-04-17
> **Source:** [github.com/Tencent-Hunyuan/HY-World-2.0](https://github.com/Tencent-Hunyuan/HY-World-2.0)
> **License:** Open-source (permissive)
> **Stars:** ~924 (as of Apr 17, 2026)
> **Release Date:** April 16, 2026

---

## Summary

**Verdict: HIGHLY RELEVANT** — HY-World 2.0 is a state-of-the-art multi-modal 3D world model from Tencent that could serve as a **procedural world-generation engine** for slop-art-online. It converts text prompts or images into persistent, navigable 3D worlds (meshes, 3DGS) that are importable into game engines — exactly the kind of "build a world, keep it forever" pipeline that would differentiate an MMORPG.

---

## What HY-World 2.0 Is

A **3D world model framework** with two core capabilities:

### World Generation (text/image → 3D)
A four-stage pipeline:
1. **HY-Pano 2.0** — Text or image → 360° panorama (coming soon)
2. **WorldNav** — Panorama → camera trajectory planning (coming soon)
3. **WorldStereo 2.0** — Panorama → 3DGS world (coming soon, interim: [WorldStereo](https://github.com/FuchengSu/WorldStereo))
4. **WorldMirror 2.0 + 3DGS** — Composition & splatting learning

### World Reconstruction (video/images → 3D)
**WorldMirror 2.0** — A unified feed-forward model (~1.2B params) that takes multi-view images or video and simultaneously predicts depth, surface normals, camera parameters, point clouds, and 3DGS attributes in a **single forward pass**. Supports flexible resolution (50K–500K pixels).

---

## Key Differentiator vs Video World Models

| | Video World Models (Genie 3, Cosmos, HY-World 1.5) | HY-World 2.0 |
|---|---|---|
| Output | Pixel videos (non-editable) | Real 3D assets (meshes, 3DGS, point clouds) |
| Duration | ~1 min max | Unlimited — assets persist |
| 3D Consistency | No (flickering across views) | Native |
| Real-Time Rendering | Per-frame inference, high latency | One-time gen, then real-time |
| Controllability | Weak | Physics collision, precise control |
| Cost | Accumulates with every interaction | One-time generation |
| Engine Compat | Video only | Blender/UE/Unity/Isaac |

---

## Currently Available (Apr 16, 2026)

| Component | Status | Details |
|---|---|---|
| Technical Report | Released | [PDF](https://3d-models.hunyuan.tencent.com/world/world2_0/HY_World_2_0.pdf) |
| WorldMirror 2.0 code | Released | Python/PyTorch, diffusers-like API |
| WorldMirror 2.0 weights | Released | HuggingFace (`tencent/HY-World-2.0`) |
| Full generation pipeline | Coming soon | WorldNav + WorldComposition |
| HY-Pano 2.0 | Coming soon | Use [HunyuanWorld 1.0](https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0) as interim |
| WorldStereo 2.0 | Coming soon | Use [WorldStereo](https://github.com/FuchengSu/WorldStereo) as interim |
| WorldNav | Coming soon | Camera trajectory planning algorithm |

---

## Python API Example (WorldMirror 2.0)

```python
from hyworld2.worldrecon.pipeline import WorldMirrorPipeline

pipeline = WorldMirrorPipeline.from_pretrained('tencent/HY-World-2.0')
result = pipeline('path/to/images')
# Output: 3DGS, meshes, point clouds, depth maps, normals, camera params
```

CLI mode also available, as well as a Gradio web demo.

---

## Output Format

- **Meshes** — Standard triangle meshes
- **3D Gaussian Splattings (3DGS)** — Neural rendering format
- **Point clouds** — Sparse and dense variants
- **Depth maps & normals** — Per-pixel surface geometry
- **Camera parameters** — Intrinsics + extrinsics

All formats are standard and can be converted to `.glb`/`.gltf` for import into **Bevy** (the game engine used in slop-art-online).

---

## System Requirements

- Python 3.10+
- CUDA 12.4+ (GPU required)
- PyTorch 2.4.0
- FlashAttention-3 (recommended) or FlashAttention-2
- Multiple GPU support via FSDP

---

## Integration with slop-art-online

### Architecture Fit

Your project already has the right patterns for this:

```
slop-art-online architecture:
  ┌─────────────────────────────────────────────┐
  │ SpacetimeDB (Rust WASM)                     │
  │   - Reducers (deterministic game logic)     │
  │   - Schedulers (NPC tick, cycles)           │
  └──────────────┬──────────────────────────────┘
                 │ subscribes to
                 ▼
  ┌─────────────────────────────────────────────┐
  │ LLM Bridge (Rust async service)             │
  │   - Subscribes to NpcPendingDecision        │
  │   - Stateless, falls back to BTs            │
  └──────────────┬──────────────────────────────┘
                 │ similar pattern →
                 ▼
  ┌─────────────────────────────────────────────┐
  │ HY-World Bridge (proposed service)          │
  │   - Subscribes to world generation requests │
  │   - Calls Python HY-World 2.0 pipeline      │
  │   - Converts 3DGS/mesh → .glb → Bevy asset  │
  │   - Falls back to existing level data       │
  └──────────────┬──────────────────────────────┘
                 │ returns asset path
                 ▼
  ┌─────────────────────────────────────────────┐
  │ Bevy Client (Rust/JS)                       │
  │   - Loads generated world as asset          │
  │   - SpacetimeDB syncs player state          │
  └─────────────────────────────────────────────┘
```

### Use Cases

1. **Procedural dungeon/level generation** — NPCs "dream" new areas using text descriptions; HY-World generates the 3D world; SpacetimeDB persists it
2. **Player-created worlds** — Players describe or upload images of locations; HY-World converts them to playable 3D areas
3. **Environmental reconstruction** — Real-world photo/video → in-game location (digital twin feature)
4. **Dynamic content updates** — Events or seasons trigger new world generation for limited-time areas

### Technical Considerations

- **Language mismatch**: HY-World 2.0 is Python/PyTorch; your project is Rust. You'd need a service bridge (like your existing LLM bridge)
- **GPU requirement**: Needs CUDA GPU. Your GB10 Spark (128GB VRAM) can run this comfortably
- **Asset conversion**: 3DGS/mesh output → `.glb` → Bevy asset pipeline needed (Blender Python API or `trimesh`/`gltf` crates)
- **Determinism**: SpacetimeDB reducers must be deterministic; world generation would need to happen outside the reducer, with only the deterministic result (asset path, tile layout) fed back
- **Latency**: World generation is non-trivial compute; should be async (scheduler-based), not blocking

---

## Comparative Analysis: HY-World 2.0 vs. Lyra 2.0

### Lyra 2.0 — Overview

**NVIDIA** research project, released April 14, 2026 (2 days before HY-World 2.0).

- **Model:** 14B-parameter CNN/Transformer, built on WAN-14B architecture
- **Input:** Single image
- **Output:** Explorable 3D worlds (video → 3DGS/mesh)
- **Paper:** [arXiv:2604.13036](https://arxiv.org/abs/2604.13036)
- **License:** **NVIDIA Internal Research License** — NOT open source. Cannot be used in production, sale, or distribution.
- **GitHub:** [github.com/nv-tlabs/lyra](https://github.com/nv-tlabs/lyra)

**Architecture:** Two-stage "generative reconstruction" approach:
1. Generates a long-range camera-controlled walkthrough video with 3D consistency
2. Lifts the video sequence into explicit 3D (3DGS + meshes) via feed-forward reconstruction

Key innovation: addresses **spatial forgetting** (per-frame geometry as information routing) and **temporal drifting** (self-augmented training with degraded outputs) for long-horizon scene generation.

---

### Head-to-Head Comparison

|| Feature | **HY-World 2.0** (Tencent) | **Lyra 2.0** (NVIDIA) |
||---|---|---|
|| **Source** | Tencent HY Team | NVIDIA SIL Lab |
|| **Release Date** | April 16, 2026 | April 14, 2026 |
|| **License** | Open (permissive) | NVIDIA Internal Research Only — not for production or commercial use |
|| **Code** | Partially open (WorldMirror 2.0 released; full gen pipeline coming soon) | Open source code available on GitHub |
|| **Model Size** | ~1.2B params (WorldMirror) | 14B params |
|| **Input** | Text, single image, multi-view images, video | Single image only |
|| **Output** | Meshes, 3DGS, point clouds, depth, normals, camera params | 3DGS, meshes (lifted from generated video) |
|| **Generation Pipeline** | 4-stage: HY-Pano → WorldNav → WorldStereo → WorldMirror | 2-stage: video gen → 3D reconstruction |
|| **3D World Gen** | Full pipeline (text/image → 3D world) | Single image → walkthrough → 3D world |
|| **World Reconstruction** | Yes (multi-view/video → 3D) | N/A (generative only) |
|| **Game Engine Export** | Unity, Unreal Engine, Blender, Isaac | Isaac Sim (robotics focus) |
|| **Character Mode** | Physics-aware character exploration | Camera-controlled video + point cloud GUI |
|| **Embodied AI** | General purpose | Robotics/simulation focused |
|| **Real-Time Rendering** | Yes | Yes |
|| **Current Availability** | Inference code + weights (WorldMirror 2.0) | HF weights; code on GitHub |

---

### Key Differences

**1. Licensing — The Dealbreaker**

HY-World 2.0 is open-source and usable in a commercial project like slop-art-online. Lyra 2.0 carries an **NVIDIA Internal Research License** that explicitly prohibits:
- Production use
- Generation of works for sale or distribution
- Distribution, deployment, or sublicensing of the model

Lyra is strictly for academic research. For a game project, it's not a viable option.

**2. Scale and Capability**

| | HY-World 2.0 | Lyra 2.0 |
||---|---|
| Model size | 1.2B params | 14B params (12x larger) |
| Text input | Yes (world generation) | No |
| Reconstruction | Yes (real scenes) | No |
| 3D consistency | Native 3D output | Video-first, then lifted to 3D |

Lyra 2.0 is significantly more powerful as a generative model. Its 14B parameters and two-stage video-then-3D approach gives it superior visual fidelity and longer-horizon consistency. HY-World 2.0's 1.2B WorldMirror is the currently released part — the full 4-stage generation pipeline is "coming soon."

**3. Architecture Philosophy**

| | HY-World 2.0 | Lyra 2.0 |
||---|---|
| Approach | Direct 3D synthesis (feed-forward to meshes/3DGS) | Generative reconstruction (video → 3D) |
| 3D first or video first? | 3D first — outputs are persistent 3D assets from the start | Video first — generates camera-controlled video, lifts to 3D after |
| Physics support | Physics-aware collision, character mode | Isaac Sim for robotics simulation |

HY-World produces persistent 3D assets directly, which is more natural for game engines. Lyra generates walkthroughs first (like a video) and extracts 3D after — a different paradigm that trades some directness for potentially higher visual quality from the video model.

**4. Maturity**

Both are extremely recent (released ~2 weeks apart). Neither has a fully open, production-ready codebase:
- HY-World 2.0 has partial release (WorldMirror 2.0 only; full generation code coming soon)
- Lyra 2.0 has HF weights + GitHub code, but the license blocks any real use

---

### Verdict for slop-art-online

**HY-World 2.0 is the practical choice** — it's open, supports text prompts (critical for NPC/player-driven generation), and outputs directly into game engines. The 1.2B model is lighter weight too.

**Lyra 2.0 is more academically interesting** — the 14B model and video-first approach may produce higher quality visuals. Its "spatial memory" technique (per-frame geometry routing) and drift-correction training are clever research contributions worth studying. The license makes it unusable for your project, but the paper is worth reading for techniques that could be adapted.

If HY-World's full generation pipeline (coming soon) matches Lyra's quality, HY-World would be the clear winner. The key thing to watch: does the "coming soon" generation pipeline deliver?

---

### Related Projects & Alternatives

|| Project | What it does | Relevance |
||---|---|---|
|| [HunyuanWorld 1.0](https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0) | Previous version of HY-World | Interim for panorama gen |
|| [WorldStereo](https://github.com/FuchengSu/WorldStereo) | Panorama → 3DGS (v1) | Interim for WorldStereo 2.0 |
|| [WorldMirror](https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror) | Multi-view → 3D reconstruction | Predecessor to WorldMirror 2.0 |
|| [LYRA (NVIDIA)](https://github.com/nv-tlabs/lyra) | 14B single-image → explorable 3D worlds (video-first) | Research only — license prohibits production use |

---

## Next Steps (Recommended)

1. **Prototype**: Run WorldMirror 2.0 on the GB10 Spark to verify GPU compatibility and output quality
2. **Convert pipeline**: Build a Blender/Python script that converts 3DGS/mesh output to `.glb`
3. **Bridge service**: Implement a lightweight Rust async service (like LLM bridge) that subscribes to world-generation requests and calls the Python pipeline
4. **SpacetimeDB integration**: Create reducers that handle the generated world's game logic (NPC placement, player zones, etc.)
5. **Bevy asset loading**: Integrate `.glb` loading into the Bevy client using the `gltf` or `bevy_asset` system

---

## References

- [GitHub Repo](https://github.com/Tencent-Hunyuan/HY-World-2.0)
- [HuggingFace Models](https://huggingface.co/tencent/HY-World-2.0)
- [Technical Report (PDF)](https://3d-models.hunyuan.tencent.com/world/world2_0/HY_World_2_0.pdf)
- [Official Site](https://3d-models.hunyuan.tencent.com/world/)
- [Live Demo (sceneTo3D)](https://3d.hunyuan.tencent.com/sceneTo3D)
- [Discord](https://discord.gg/dNBrdrGGMa)
- [Contact](mailto:tengfeiwang12@gmail.com) — Tengfei Wang
- [HY-World 1.0](https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0)
