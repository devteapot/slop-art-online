# Vendored skills

Two skills in `.agents/skills/` are vendored: `create-verification-skill` and `maintain-verification-skill`. Everything else there is project-authored.

- Source: https://github.com/michael-denyer/pstack-claude
- Revision: `55430ba22ccc751ab608422761aff14b2f063e5d`
- Source directory: `plugins/pstack/skills/`
- Installed: 2026-10-04
- License: MIT. The license and the upstream notice are in [licenses/](licenses/). The notice also lists upstream skills that this project no longer carries.
- Local change: the line pointing Codex users to a platform mapping was removed from both skills on 2026-11-11.
- Local change, 2026-11-12 (branch `skills-layout`): both skills now require one new validation file per run (`references/validation/<YYYY-MM-DD>-<HHMM>-<branch-or-run>.md`, never edited afterwards), a stable `description` with feature detail kept in the feature map (its rows sorted alphabetically), and cases registered where they are defined instead of in a central list. Reason: 18 of about 49 merges into main conflicted, nearly all in the single `references/validation.md` per skill, the one-line `description`, the central case lists of `verify_minds.py` and `verify-ui/scripts/check.py`, and the feature-map tables, which every branch edited at the same spot. `create-verification-skill` has the rules under "Generate the skill" and "Seed the feature map"; `maintain-verification-skill` under "Edit scope", "Index hygiene" and after "Ship or stop". Keep these changes when updating the skills from upstream.

The rest of that distribution, the Cursor variant in `.cursor/` and the project's model sheets were removed on 2026-11-11. Their last state is in git history before that date.

## Project verification

The verification skills are project-authored. `verify` in `.agents/skills/verify/` is the entry point and shared harness. Each surface has its own `verify-<surface>` skill: core, generation, client, player, ui, minds, llm and knowledge. They were created with `create-verification-skill` on 2026-10-04, `verify-ui` on 2026-11-11. Claude Code discovers each skill through a relative link in `.claude/skills/`. Each skill records each real run in its own file in `references/validation/` (the newest files are the last validated runs; `history.md` holds the single record kept until 2026-11-12), and `verify/scripts/latest_validation.py` lists the newest per surface. The `AGENTS.md` section "Verification surfaces" says when to run each skill and when to run `maintain-verification-skill`.

To update the two vendored skills, install the source directory at a new pinned revision into a temporary destination, review the changes, replace the two skill directories and update this record.
