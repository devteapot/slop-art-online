# Vendored skills

This is the provenance record for the skills vendored into this project from the upstream pstack plugin, for Codex, Claude Code, Cursor, and Mistral Vibe. Model choice is not set here or in the skills: see "Models and coordination" in the root `AGENTS.md`. The root `AGENTS.md` defines the compatibility requirement for every project skill and setup change. Changes made through one agent apply to the shared project setup and all affected adapters unless the user explicitly limits their scope.

## Codex and Claude Code

Codex uses `.agents/skills/`. Claude Code uses relative symlinks in `.claude/skills/` pointing to that shared tree.

Project instructions live only in root `AGENTS.md`. Claude Code's default `claude-md-or-agents-md` mode loads it when no project `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` is present. The installed Claude Code version was 2.1.289 when verified; no user override of this mode was configured. A separate `CLAUDE.md` import adapter is unnecessary. Skill discovery links remain in `.claude/skills/`. The existing `.claude/commands/` (`update-docs`, `update-diagrams`) are unrelated to the vendored skills and unchanged. See [Claude Code AGENTS.md support](https://code.claude.com/docs/en/memory#agentsmd).

Mistral Vibe uses the same `.agents/skills/` tree through its standard project skill discovery and reads root `AGENTS.md` in trusted projects. No separate Mistral skill copy is needed. See [Vibe skill discovery](https://github.com/mistralai/mistral-vibe#skill-discovery). Native workflow capabilities still require the active runtime's tool mapping or the documented fallback; shared discovery does not imply identical tools across agents.

- Source: https://github.com/michael-denyer/pstack-claude
- Revision: `55430ba22ccc751ab608422761aff14b2f063e5d`
- Source directory: `plugins/pstack/skills/`
- Installed: 2026-10-04
- Contents: 32 public skills and 24 principle references (56 directories), including bundled scripts, runtime mappings, and license notices.

Start a task with `Use poteto-mode to <describe the task>`, or request a specific skill such as `how`, `tdd`, or `interrogate`. The skills are available on the next turn.

This is a skills-only installation. Automatic plugin routing hooks and global model configuration are not installed, and the model sheets the skills mention are not used. The Codex runtime mapping is in `skills/poteto-mode/references/codex-tools.md`. Follow the project's `AGENTS.md` and the active runtime's tool and delegation instructions when using these workflows. On Claude Code, read `AGENTS.md` for the repository instructions before starting work.

## Project verification

The project verification skills are project-authored, not vendored. `verify` in `.agents/skills/verify/` is the entry point and shared harness. Each surface has its own `verify-<surface>` skill: core, generation, client, player, minds, llm and knowledge. The browser observer has no skill until a proper game UI replaces it. They were created with `create-verification-skill` on 2026-10-04. Claude Code and Cursor discover each skill through relative links in `.claude/skills/` and `.cursor/skills/`; Codex and Mistral Vibe read the shared tree. Each skill records its last real run in `references/validation.md`. The `AGENTS.md` section "Verification surfaces" says when to run each skill and when to run `maintain-verification-skill`.

## Cursor

Cursor uses the original upstream skills in `.cursor/skills/`, with its bundled subagent definitions in `.cursor/agents/` and license in `.cursor/LICENSE`.

- Source: https://github.com/cursor/plugins/tree/main/pstack
- Revision: `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`
- Source directory: `pstack/skills/`
- Installed: 2026-10-04
- Contents: 50 upstream skills and principle references.

Request `poteto-mode` by name or use `/poteto-mode` in Cursor. Plugin automations and marketplace registration are not included.

To update, install each source directory at a new pinned revision into a temporary destination, review the changes, replace the corresponding vendored skill directories and Cursor agents/license, and update this record. Claude Code's links continue to use the shared tree. To uninstall, remove the installed skill directories, Claude Code links, Cursor agents/license, and this record, preserving any separately added skills or agents.
