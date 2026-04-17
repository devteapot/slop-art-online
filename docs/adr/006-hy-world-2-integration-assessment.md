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

## Related Projects & Alternatives

| Project | What it does | Relevance |
|---|---|---|
| [HunyuanWorld 1.0](https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0) | Previous version of HY-World | Interim for panorama gen |
| [WorldStereo](https://github.com/FuchengSu/WorldStereo) | Panorama → 3DGS (v1) | Interim for WorldStereo 2.0 |
| [WorldMirror](https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror) | Multi-view → 3D reconstruction | Predecessor to WorldMirror 2.0 |

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
