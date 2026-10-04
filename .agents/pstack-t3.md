# P-Stack T3 Code adapter

Read this with `pstack-models.md` before using a P-Stack workflow inside T3 Code. This is a project instruction adapter, not a plugin or a new server. T3 performs orchestration through its existing tools.

## Rerun setup

When `setup-pstack` is invoked, refresh `orchestrator_capabilities`, load this project's policy, and show the concrete role selections and supported requested options. Apply requested role or effort changes to `.agents/pstack-models.md`, validating explicit provider/model choices against the catalog. Keep live-discovery policies for roles the user has not pinned. Do not run the vendored global-sheet writing, global instruction import, or SessionStart-hook configuration steps. Hooks are absent in this installation; enabling automatic routing would be a separate requested change. Outside T3, keep setup project-local and validate choices with the native runtime's discovery tools.

For reasoning configuration, read `.agents/pstack-effort.json`. Support customized model baselines, role-wide overrides, and role/model pair overrides as well as the original setup choices `unlimited — keep max`, `large — xhigh reasoning`, `medium — high reasoning`, and `small — medium reasoning`. The session budget uses saved baselines and otherwise retains provider settings. Show the effective effort for every selected model and role before saving requested changes. Store model baselines in `modelEfforts`, role-wide overrides in `roleEfforts`, and role/model overrides in `roleModelEfforts`; keep model selection in `.agents/pstack-models.md`. A saved project budget is a fallback behind those explicit baselines. If the user requests applying a preset to every role, resolve the preset for every selected role/model and save the resulting role/model efforts, showing any lowered values. Validate every role against the live catalog with the helper below. Report any preset lowering or unsupported exact override. Preserve settings the user has not requested to change. Keep Astra manual-only even under unlimited or high-effort presets.

## UI ownership

GPT-6.1-Sol is the default implementation lead and coordinator; Claude Opus 5.5 handles judgment and leads UI design and implementation. Resolve both against the live catalog and use their saved high effort baselines. UI ownership applies to visible behavior, interactions, layout, styling, Bevy presentation and input, and accessibility, regardless of file extension. It takes precedence over generic feature, refactoring, bug-fix, and performance role labels for the UI portion.

For a mixed feature, assign the UI portion to a Claude Opus child task while Sol handles server operations, protocol, underlying logic, and integration. Agree on the server/client contract first and assign explicit file ownership. A Bevy client or viewer file can contain both presentation and underlying state logic; split cohesive work where possible and sequence changes to shared files rather than editing them concurrently. Include the relevant client documentation (`docs/LIVING_CORE.md`, `docs/BEVY_BROWSER_CLIENT.md`) and the actual observed running UI in the UI brief.

For UI-only work, a user-selected Opus parent can lead directly. Otherwise the current parent coordinates an Opus UI lead child task. This adapter cannot change the current thread's model. If the preferred Claude route is unavailable, refresh the catalog and use another eligible provider exposing the exact Opus model. If no eligible route exists, report that UI work is unavailable and continue independent non-UI work. Do not silently substitute Sol for UI ownership, including outside T3.

## Bounded GLM work

Use GLM 5.3 through Mistral Vibe for quick, easy, narrowly scoped non-UI changes and bounded batches of mechanical edits. Resolve the `small changes and bounded mechanical work` role to `acpRegistry_mistral_vibe` / `glm-5-3` and validate its max-effort baseline with the effort helper. This role overrides generic feature, refactoring, bug-fix, or swarm defaults only when the cause and required behavior are clear. Keep UI work with Opus and broad or uncertain work with Sol/judgment.

Sol coordinates the assignment, gives GLM clear file ownership and acceptance checks, then reviews and integrates its result. If the work reveals unknown causes, architectural decisions, or cross-cutting effects, return it to the coordinator before expanding scope. Preserve Mistral Vibe's configured approval mode. If GLM is unavailable, resolve another eligible route for the exact model or use Sol and report the fallback.

## Resolve and dispatch

1. Call `orchestrator_capabilities` at workflow start. Use the catalog's exact provider instance IDs, model IDs, advertised model options, capability flags, and constraints. Include configured custom providers and models. Tool names can have an MCP prefix.
2. Resolve each needed role with `pstack-models.md` and its effort with `.agents/scripts/pstack-effort.ts`. Apply a task-specific budget or effort request when provided. Keep a small task-local record of role, provider instance, model, and resolved options. Refresh the catalog after an availability error rather than relying on the setup date's models.
3. Prefer native subagent tools for same-provider work only when they can express the selected model and requested options. Use `delegate_task` for cross-provider work, native-unsupported models, or explicitly T3-owned child work. Do not replace a selected model merely because a native tool cannot run it.
4. Pass provider and model separately in `target`. Pass options using the selected model's advertised IDs. For example, a reasoning option can be `reasoningEffort`, `effort`, or `thinking`; these are not interchangeable. A full T3 Claude model ID is valid for T3 dispatch even when native Claude's Agent tool requires a family alias.
5. Leave runtime and interaction modes inherited. Pass only the helper's validated effort option. Omit it when the resolved effort is session, which occurs when explicitly requested or when neither a baseline nor a preset applies. Same-provider effort inherits where supported when no override is sent; cross-provider effort then uses the target provider's configured or default value and need not match the parent's effort. Provider-specific approval options, such as Mistral Vibe's `mode`, also keep their configured values and can require user interaction even when T3 runtime mode is full access. Do not weaken permissions or modify provider configuration to make a dispatch succeed. If a child waits on approval, report that state and use the runtime's normal approval flow or choose an eligible alternative, reporting reduced panel diversity when relevant. Do not duplicate or abandon a live task silently.

## Resolve effort options

Write the structured catalog returned by `orchestrator_capabilities` to a temporary JSON file. The helper reads that snapshot and the project effort configuration; it does not call models, dispatch work, or change provider settings.

```sh
bun .agents/scripts/pstack-effort.ts --catalog /tmp/pstack-catalog.json --provider cursor --model grok-4.7 --role "arena runners" --budget large
```

Omit `--budget` to use the saved model/role baselines and project budget. Use `--effort` for an exact task-specific effort override. Resolve precedence as documented in `pstack-models.md`. A `ready` result contains `options` suitable for `delegate_task.target.options`; preserve its provider/model pair. Report a non-null `adjustment` when a preset is lowered. A `needs-choice` result must be resolved before dispatch; do not ignore it and silently run at the provider default. Invalid inputs fail with a diagnostic.

Run the resolver's fake-catalog tests with `bun test ./.agents/scripts/pstack-effort.test.ts`. These cover provider option differences and model/role precedence without issuing model calls.

Example dispatch shape, with values resolved from the live catalog:

```json
{
  "task": "Self-contained task brief and relevant file paths",
  "target": {
    "providerInstanceId": "catalog-provider-instance-id",
    "model": "catalog-model-id"
  },
  "mode": "async",
  "clientRequestId": "unique-stable-request-id-for-this-round"
}
```

The placeholders above are not model IDs. Validate the target before calling the tool. Include the project instructions, selected role, relevant P-Stack skill paths, acceptance criteria, and any previous review findings in the child brief. For an implementation delegate, tell it to read the installed `poteto-mode/SKILL.md` before working. The caller reviews the resulting diff and owns integration.

## Child task lifecycle

- Retain each returned `taskId`. Use `task_status` when a result is needed during the current turn, and `task_cancel` for cancellation. T3 delivers async completion notifications, so do not create a separate polling watcher.
- Every delegated review round is a new `delegate_task` call with a distinct request ID, stable across retries of that round. Include the original brief, prior findings, responses, and unresolved objections. Do not send another review round to `childThreadId`.
- A child thread is task backing storage. Do not create top-level conversations for P-Stack subagents. Use `t3_thread_launch` or `create_threads` only when the user explicitly requests separate conversations.
- `delegate_task` inherits this thread's project, branch, and worktree. It does not provide an isolated checkout. Divide concurrent implementation ownership by files; avoid simultaneous writes to shared files. For Arena candidates editing the same files, have child tasks produce proposed patches in separate output directories without changing the shared checkout; the parent applies and verifies one candidate at a time, restoring the task baseline between candidates while preserving pre-existing user changes. Do not run the vendored concurrent worktree-editing steps through `delegate_task` as if its binding were isolated. Use native isolated-workspace delegation only when the native tool actually supports it. If the user explicitly requests independent top-level T3 conversations, `t3_thread_launch` can select their workspace through `workspaceStrategy`; it is not a substitute for child delegation. Running `cd` in a child does not change its T3 thread binding.
- On a provider failure, inspect the error and refresh availability. Choose an eligible fallback using the project policy and report the substitution. Do not duplicate a live task, repeatedly retry a failing provider, or change authentication or permissions without authorization.

## Other T3 facilities

For UI work, prefer T3's collaborative `preview_*` tools when available. For PR monitoring, prefer `watch_pull_request` and let T3 wake the thread. Register worked-on PRs with `link_pull_request` when available. For persistent scheduled work explicitly requested by the user, use T3's `schedule_task` with a structured schedule object. P-Stack's standalone browser, PR watcher, and looping examples do not override these runtime instructions.

Outside T3, use the native fallback in `pstack-models.md`. No global model sheets or plugin hooks are required for this project adapter.
