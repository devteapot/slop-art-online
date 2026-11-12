# Looks: the key on every seen person

Since `look-1-auth` (2026-11-12, docs/LOOK.md). Each person has one private `look` row (their person entry `lp_…`, never sent, and the line `lk_…` they wear for their band); `look_line` holds the world's lines. Both are private in every build. A client receives a look only as the `look` column of its `seen_characters` rows: the `lk_` key of the line, for anyone it sees, made out or too far away to make out (there is no far stand-in), its own character included. Animals and people with no look row (a world from before looks, or a seed without `looks`) have `look` "". Names stay hidden by the far label as before. The client draws the line its book (char-4's `assets/characters/looks.json`) holds under the key.

## Sub-features

- SQL on `look` and `look_line` is refused to a player identity and anonymously (also in `drive.py`'s `PRIVATE` inventory, and `relook` in its `ADMIN` list: refused to every non-admin with "admin only").
- Every person row of `seen_characters` carries a key matching `^lk_[0-9a-f]{16}$`, equal to that person's `look.line` and to a `look_line` key, and equal to (or containing) no name or name slug.
- A far row (the overlay's `far` past 4 m) carries its key too, with no name and the far label; the near one is "a stranger" with its key. No field of any row holds a hex colour.
- An animal's row has `look` "". Someone out of sight (60 m) has no row.
- A second subscription (a new connection with the same identity) holds the same rows of the people held still, key for key.

## Driving it

On a launched and doctored `client-*` run whose seed has looks (`$V launch --run "$R" --seed plan-test`, the fixture generation `fixture-1`; Cullet's own data since look-1, `--seed cullet`):

```bash
.agents/skills/verify-client/scripts/look_rows.py --run "$R"
```

It joins the run's player, spawns three minded strangers, holds them still and installs the far overlay (as `far_label.py` does; the shipped script again at the end), places the player beside a deer when the world has one, and streams `seen_characters` through the SDK probe twice. Admin calls (`install_script`, `spawn_crowd`, `set_behavior`, `place_at`) set the scene. Evidence: `look-seen-*.jsonl` (each stream, named with the time so a rerun never overwrites), `look_rows.json`.

## Gotchas

- The key's hash rule (SHA-256 over the drawn fields' canonical JSON) is the generator's; this check cannot recompute it from a row, because the line itself is in the client's book, not on the authority. verify-generation checks char-4's hash cases.
- Deer wander off between the two streams: the reconnect check compares the people held still only.
