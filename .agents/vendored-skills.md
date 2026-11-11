# Vendored skills

Two skills in `.agents/skills/` are vendored: `create-verification-skill` and `maintain-verification-skill`. Everything else there is project-authored.

- Source: https://github.com/michael-denyer/pstack-claude
- Revision: `55430ba22ccc751ab608422761aff14b2f063e5d`
- Source directory: `plugins/pstack/skills/`
- Installed: 2026-10-04
- License: MIT. The license and the upstream notice are in [licenses/](licenses/). The notice also lists upstream skills that this project no longer carries.
- Local change: the line pointing Codex users to a platform mapping was removed from both skills on 2026-11-11.

The rest of that distribution, the Cursor variant in `.cursor/` and the project's model sheets were removed on 2026-11-11. Their last state is in git history before that date.

## Project verification

The verification skills are project-authored. `verify` in `.agents/skills/verify/` is the entry point and shared harness. Each surface has its own `verify-<surface>` skill: core, generation, client, player, minds, llm and knowledge. They were created with `create-verification-skill` on 2026-10-04. Claude Code discovers each skill through a relative link in `.claude/skills/`. Each skill records its last real run in `references/validation.md`. The `AGENTS.md` section "Verification surfaces" says when to run each skill and when to run `maintain-verification-skill`.

To update the two vendored skills, install the source directory at a new pinned revision into a temporary destination, review the changes, replace the two skill directories and update this record.
