# ADR 012 — Browser-hosted Bevy foundation client

Status: implemented bounded development slice, 2026-09-05.

The user needs to observe and join the real simulation in the game client, with a browser URL as the primary development entry point. The previous HTTP inspector did not provide the Bevy game experience. Native-only framing in earlier planning is superseded by this delivery target.

Compile the existing Bevy client to WASM and share its foundation rendering, selection, UI and input systems with optional native builds. Keep legacy gameplay behind its existing default feature. Use a canvas-only HTML launch shell and Bevy's WebGL2 renderer for the tested browser path. Retain Bevy 0.18.1; upgrade SpacetimeDB module, Rust SDK and generated bindings to released 2.1.0, the first released SDK with browser support. Run that server against separate storage so existing 2.0.1 experiments remain intact.

SpacetimeDB remains the sole authority. A private identity/run/actor grant table drives a caller-specific view. Participant projections contain own subjective state and eligible observations; observers receive world truth and causal audit summaries. Human input derives actor ownership on the server and uses the same skill executor. A private scheduled clock implements time controls independently of rendering and external inference.

A loopback Rust host serves WASM, provisions development sessions and fresh runs, reads preserved archives, and optionally runs existing async model adapters. Its HttpOnly same-origin session broker is intentionally a local developer privilege boundary. It is not production role provisioning. Operator/provider credentials remain outside the browser; SDK identities are anonymous and freshly enrolled rather than authenticated by a token embedded in a browser URL.

Distinguish actual live fixture execution, configured live model reasoning and preserved read-only model archives in both the data and game UI. Fixture behavior does not prove generated model quality. Current evidence and reproduction instructions are in [the browser client report](../BEVY_BROWSER_CLIENT.md); production authentication, richer presentation, full IME/accessibility and additional human assignments remain follow-up work.
