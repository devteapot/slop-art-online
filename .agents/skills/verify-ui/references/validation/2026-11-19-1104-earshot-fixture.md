# Earshot fixture on the island and play-test 10

Validated the `earshot-fixture` harness changes against origin/main base `d6e82af7ee2894a66d7ebb7ebbfaaa2c862e75e9`. Both runs used the real headless Bevy client on the local scoped SpacetimeDB 2.14.1 authority. The launch log marks `living/` dirty because the checkout had temporary asset links to the play-test 10 assets. Both release builds used a private target directory and `BUILD_SLOTS=1` through `build-slot`.

| Scratch world | `check.py earshot` | Say carry | Call carry | Player hearing / sight | B's distance after the move |
| --- | ---: | ---: | ---: | ---: | ---: |
| `verify-ui-earshot-base-1119`, island | 8/8 | 9 m | 22.5 m | 9 m / 11 m | 10.05 m |
| `verify-ui-earshot-play10-1119`, copied scene and overlay | 8/8 | 12 m | 30 m | 12 m / 48 m | 13.04 m |

The fixture reads the public `speech_card.carry_m` values once per run. The authority computes those cards with `carry_for` and the world's ordinary hearing. A one-shot `my_senses` query via the joined client's identity records the player's actual hearing and sight. These reads use the existing public table and sender-scoped view in the pinned 2.14.1 module, with no new subscriptions or retained rows. [SpacetimeDB tables](https://spacetimedb.com/docs/tables/) · [SpacetimeDB views](https://spacetimedb.com/docs/functions/views/)

Both residents stood east of the player on open grass at noon. Both appeared in Say initially. After tile snapping placed B beyond Say range, Say held only A and Call still held both, proving B stayed visible. Tab followed the authority's lists with the law on, then used the client's fallback after the law was turned off. The play-test 10 scene copy embedded the exact text of the copied `scene_laws.rhai`. The launch verified the installed overlay and doctor confirmed both worlds advanced.

Evidence stays under `.local/living/verify/ui-earshot-{base,play10}-1119/`. Each run has `ui/checks.json` and `ui/earshot/{plan.txt,scene.json,client.log,e1.json,e2.json,e3.json}` plus screenshots and Tab dumps. Console, launch and cleanup logs are under `.local/earshot/`. Cleanup verified that both database names stopped resolving and removed both scratch module copies.

The drive covered the box and Tab behavior. It made no model calls and did not exercise speech delivery, physical input or performance.
