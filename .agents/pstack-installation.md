# P-Stack installation

P-Stack is installed locally in this project for Codex, Claude Code, Cursor, and Mistral Vibe. The root `AGENTS.md` defines the compatibility requirement for every project skill and setup change. Changes made through one agent apply to the shared project setup and all affected adapters unless the user explicitly limits their scope.

## Codex and Claude Code

Codex uses `.agents/skills/`. Claude Code uses relative symlinks in `.claude/skills/` pointing to that shared tree.

Project instructions live only in root `AGENTS.md`. Claude Code's default `claude-md-or-agents-md` mode loads it when no project `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` is present. The installed Claude Code version was 2.1.289 when verified; no user override of this mode was configured. A separate `CLAUDE.md` import adapter is unnecessary. Skill discovery links remain in `.claude/skills/`. The existing `.claude/commands/` (`update-docs`, `update-diagrams`) are unrelated to P-Stack and unchanged. See [Claude Code AGENTS.md support](https://code.claude.com/docs/en/memory#agentsmd).

Mistral Vibe uses the same `.agents/skills/` tree through its standard project skill discovery and reads root `AGENTS.md` in trusted projects. No separate Mistral skill copy is needed. See [Vibe skill discovery](https://github.com/mistralai/mistral-vibe#skill-discovery). Native workflow capabilities still require the active runtime's tool mapping or the documented fallback; shared discovery does not imply identical tools across agents.

- Source: https://github.com/michael-denyer/pstack-claude
- Revision: `55430ba22ccc751ab608422761aff14b2f063e5d`
- Source directory: `plugins/pstack/skills/`
- Installed: 2026-10-04
- Contents: 32 public skills and 24 principle references (56 directories), including bundled scripts, runtime mappings, and license notices.

Start a task with `Use poteto-mode to <describe the task>`, or request a specific skill such as `how`, `tdd`, or `interrogate`. The skills are available on the next turn.

This is a skills-only installation. Automatic plugin routing hooks and global model configuration are not installed. The Codex runtime mapping is in `skills/poteto-mode/references/codex-tools.md`. Follow the project's `AGENTS.md` and the active runtime's tool and delegation instructions when using these workflows. On Claude Code, read `AGENTS.md` for the repository instructions before starting work.

## T3 Code configuration

The shared project model policy is in [pstack-models.md](pstack-models.md). [pstack-t3.md](pstack-t3.md) describes how to apply it through T3 Code. These project files replace separate global model sheets for this installation. They do not change T3 Code's provider settings or the current session's model.

For delegated work, resolve the provider instance, model ID, and supported options from the live `orchestrator_capabilities` catalog. Include all enabled providers and configured custom models when selecting candidates. Do not treat Codex, Claude Code, and Cursor as the list of available model providers.

GPT-6.1-Sol is the default implementation lead and coordinator. Claude Opus 5.5 handles judgment and leads all UI design and implementation, including visible behavior, interactions, layout, styling, Bevy presentation and input, and accessibility. This UI assignment takes precedence over generic task labels and does not depend on file extension. Difficult tasks use the strongest suitable model available in the catalog. Review, architecture, and arena panels choose candidates from distinct model families where available.

For mixed features, Sol handles server operations, protocol, underlying logic, and integration while an Opus child task owns the UI portion. Agree on contracts and file ownership before parallel work, and sequence changes to shared files. For UI-only work, use a user-selected Opus parent or an Opus UI lead child task. Follow the relevant client documentation and the actual observed running UI. This configuration does not switch the current thread's model.

GLM 5.3 through Mistral Vibe is the bulk-work delegate for quick, easy, narrowly scoped non-UI changes and bounded batches of mechanical edits. It runs at max effort, with Sol coordinating, reviewing, and integrating. This role can handle simple known-cause fixes, but broad changes and unknown-cause investigation stay with Sol or the judgment role. UI work remains with Opus even when small. If a GLM assignment reveals broader complexity, return it to the coordinator before expanding scope.

Reasoning settings are configured in `.agents/pstack-effort.json`. Per-model baselines, role-wide overrides, and role/model pair overrides are supported alongside the original unlimited, large, medium, and small presets. The Bun helper `.agents/scripts/pstack-effort.ts` resolves the selected settings to the model's live advertised effort option before delegation. It lowers a preset only to the highest supported level at or below its target and reports that adjustment. Exact saved baselines and role/task efforts must be supported; unsupported requests need a choice. A task-specific budget does not change the saved project settings.

The saved baselines are GLM 5.3 at max, GPT-6.1-Sol and Opus 5.5 at high, and Grok 4.7 at high. The project budget remains session for models without a baseline. Session sends no override only when no more specific baseline applies. Same-provider tasks can then inherit effort; cross-provider tasks retain the target provider's current or default effort. Unlimited preserves customized baselines, otherwise using the original max/xhigh effort pattern. It does not restore the original model assignments or change fast-mode settings.

Astra is manual-only. Difficult work now prefers Opus 5.5, with GPT-6.1-Sol as a fallback. Automatic panels, retries, or effort presets must not select Astra unless the user explicitly requests it for the task or selects it as the parent model.

Provider-specific permission and approval options remain configured by the provider. Options such as Mistral's `mode` may leave delegated work waiting for approval. This instruction adapter does not change those settings or global configuration.

Use native subagent tools for same-provider work when they support the selected model. Use T3 Code's `delegate_task` for cross-provider work, models that native tools cannot select, and explicitly T3-owned child work. Preserve the active runtime's delegation rules and track each delegated task by its returned `taskId`.

Invoke `poteto-mode` explicitly to start its workflow. Automatic routing hooks are not installed, and this configuration does not change skill-picker discovery. Outside T3 Code, use the current session model for non-UI work when the native runtime cannot discover or select other providers, and report the reduced model diversity. For UI work, try another eligible route exposing the exact Opus model if the preferred Claude route is unavailable. If none exists, report the unavailable UI role and continue independent non-UI work; do not silently substitute Sol.

## Project verification

The project verification skills are project-authored, not vendored. `verify` in `.agents/skills/verify/` is the entry point and shared harness. Each surface has its own `verify-<surface>` skill: core, generation, client, player, minds, llm and knowledge. The browser observer has no skill until a proper game UI replaces it. They were created with `create-verification-skill` on 2026-10-04. Claude Code and Cursor discover each skill through relative links in `.claude/skills/` and `.cursor/skills/`; Codex and Mistral Vibe read the shared tree. Each skill records its last real run in `references/validation.md`. The `AGENTS.md` section "Verification surfaces" says when to run each skill and when to run `maintain-verification-skill`.

## Cursor

Cursor uses the original P-Stack skills in `.cursor/skills/`, with its bundled subagent definitions in `.cursor/agents/` and license in `.cursor/LICENSE`.

- Source: https://github.com/cursor/plugins/tree/main/pstack
- Revision: `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`
- Source directory: `pstack/skills/`
- Installed: 2026-10-04
- Contents: 50 upstream skills and principle references.

Request `poteto-mode` by name or use `/poteto-mode` in Cursor. Plugin automations and marketplace registration are not included.

To update, install each source directory at a new pinned revision into a temporary destination, review the changes, replace the corresponding vendored skill directories and Cursor agents/license, and update this record. Claude Code's links continue to use the shared tree. To uninstall, remove the installed skill directories, Claude Code links, Cursor agents/license, and this record, preserving any separately added skills or agents.
