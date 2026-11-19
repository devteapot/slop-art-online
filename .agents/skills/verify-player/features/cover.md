# Cover in a player’s live projection

The actor sees the control target with the law off and loses it behind cover. Check the player’s own view, missile result and absence of extra first-sight lines.

[Shared cover proof and scratch recipe](../../../../docs/COVER_SIGHT.md#client-edits-and-scratch-recipe).

## The laws as a world ships them

`sight_on.py` checks a world whose overlay turns cover and gaze on (Cullet's since 2026-11-19, and the play-test world's), with no law set by the scene before its checks: `cover_law` as shipped, no override of a cover, gaze or facing law in `law_override` (read as the player: the table is public since `law-override`), a resident behind a trunk hidden, a control resident 4 m away on open ground seen, a terrace overlook clear, a cliff face and brush hiding, each hedge hiding (and the same pair seen with `cover_brush_on` off, its cause; the law is put back), and `human_gaze` changing the applied field, with Far seeing a resident beyond Middle's reach that Middle does not. Every check first confirms the world is unpaused and its tick advances, because the orphan guard pauses a world 120 s after its launcher exits; keep `launch` and the scene under one supervising process.

```sh
cargo run --release --manifest-path living/Cargo.toml -p living-rules --example cover_fixture -- living/seeds/cullet.json > fixture.json
R=player-sighton-$(date +%H%M%S)
"$V" launch --run "$R" --seed cullet && "$V" player --run "$R" join VerifySightOn
.agents/skills/verify-player/scripts/sight_on.py --run "$R" --fixture fixture.json \
  --hedges '[[525.0,696.0,526.3,699.8],[521.5,666.4,522.9,670.2]]'
"$V" cleanup --run "$R"
```

Cullet's two hedges are `mid_row_plot_toft_3_hedge` and `high_row_plot_garden_3_hedge` in land metres (plan origin (510, 784), plan y north). A land without brush (the island) gives `"brush": null` in the fixture; pass `--brush` with the world's `cover_brush_on` and no `--hedges`. The proof is `sight-on-proof.jsonl` in the run directory.
