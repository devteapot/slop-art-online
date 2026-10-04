# P-Stack project model policy

This project uses T3 Code's live provider catalog as the model registry. This policy applies regardless of which provider runs the parent conversation. It overrides the installed P-Stack skills' per-harness model defaults and global configuration paths. Do not write global Codex, Claude, or Cursor model sheets when configuring this project.

These are selection policies, not literal model IDs. Before dispatching a workflow role, resolve its policy to a concrete provider instance and model from `orchestrator_capabilities`. Build the workflow's model override rows in the current task context. Do not pass policy names or combined `provider:model` strings as the tool's `model` argument.

## Roles

| P-Stack role | Selection policy |
| --- | --- |
| feature, refactoring | implementation, with UI portions routed to UI lead |
| UI design, implementation, interaction, and visual verification | UI lead |
| small changes and bounded mechanical work | bulk worker |
| bug-fix | strongest |
| perf-issue | strongest |
| hillclimb | strongest |
| judgment and prose | judgment |
| strongest judgment / hardest tasks | strongest |
| how explorer | implementation |
| how explainer | judgment |
| why investigators | implementation |
| why synthesizer | judgment |
| reflect tooling | implementation |
| reflect judgment, divergent, synthesizer | judgment |
| arena runners | diverse panel |
| arena cross-judge pool | diverse panel |
| swarm workers | implementation; simple bounded non-UI batches use bulk worker; UI workers use UI lead; comparison arms use their selected models |
| architect runners | diverse panel |
| interrogate reviewers | diverse panel |

## Selection

- **parent:** use the catalog's `inheritedProviderInstanceId` and `inheritedModel`. Native `inherit-parent` and `auto` values have the same meaning.
- **implementation:** prefer `gpt-6.1-sol` through Codex for ordinary underlying logic and implementation coordination. This is an explicit project preference, independent of the parent conversation's selected provider. Prefer another eligible route exposing that exact model if Codex is unavailable, then report any necessary fallback to an eligible non-Astra parent. Explicit user choices can override this preference.
- **UI lead:** prefer `claude-opus-5-5` through Claude for every UI-related portion of work. If that route is unavailable, use another eligible provider exposing the exact model with validated options. Do not silently substitute Sol for UI work; report the unavailable route and continue independent non-UI work until an available UI model is selected. Use the saved Opus high-effort baseline.
- **bulk worker:** prefer `glm-5-3` through Mistral Vibe (`acpRegistry_mistral_vibe`) at its saved max-effort baseline for quick, easy, narrowly scoped non-UI changes and bounded batches of mechanical edits. Use this for clearly specified work with known behavior and a straightforward verification path, including simple fixes with an already established cause. Sol remains the coordinator and reviews and integrates the result. If that route is unavailable, try another eligible route exposing the exact model, then use Sol and report the substitution.
- **strongest:** select a model suited to difficult reasoning from the enabled catalog. Prefer `claude-opus-5-5` on `claudeAgent`, then `gpt-6.1-sol` on `codex`, then an eligible parent. These are preferences, not availability guarantees. Explicit user choices and newly configured suitable models can replace them. Astra is not an automatic escalation or fallback.
- **judgment:** prefer an available `claude-opus-5-5` on `claudeAgent`, then the strongest selection. Respect explicit user choices over this initial preference.
- **diverse panel:** use three distinct model families where available. Include the parent when eligible, then choose complementary models from the enabled catalog, excluding manual-only models. The initial complementary preferences are Claude Opus and Grok 4.7, with GLM 5.3 through Mistral Vibe and Mistral Medium as alternatives. Resolve GLM 5.3 as model `glm-5-3` on provider instance `acpRegistry_mistral_vibe` when that pair remains available. Treat GLM as its own model family, distinct from Mistral models on the same provider. Enabled providers and configured custom models remain eligible subject to the manual-only restriction; the named examples are not an allowlist. Avoid duplicate families when aliases or multiple providers expose the same model. If fewer than three families are usable, use the available models and state the reduced diversity. Preserve a user-requested panel size. For Arena's cross-judge, choose a family different from the parent and candidate being judged when possible.

GPT-6-Astra is manual-only across all provider routes. Use it only when the user explicitly asks for Astra for the current task or explicitly selects it as the parent model in T3. Do not select it automatically for difficulty escalation, panels, retries, or missing-model fallbacks. Its availability in the catalog does not authorize automatic use. Report reduced diversity or an unavailable role rather than casually escalating to Astra. No project effort baseline is assigned to Astra; an explicit request can include an effort level, otherwise retain its configured setting.

Use only provider instances with `canRunChildTask: true`, and only models listed for that instance. Cross-provider dispatch also requires `canRunCrossProviderChildTask: true`. Recheck availability at workflow start and after a dispatch reports a stale model or provider error. Do not substitute a disabled provider or guess a custom model ID.

When a preferred model is exposed by multiple providers, resolve each provider/model pair separately. Prefer the parent provider when it exposes the selected model, then an available dedicated provider, then another eligible provider exposing that exact model. A disabled dedicated provider does not make the model unavailable through other providers. Use the selected route's option IDs and values; identical model IDs can have different options on different providers.

## UI and underlying logic

UI scope takes precedence over a generic feature, refactoring, bug-fix, or performance label for the visible portion of a task. It includes UX and interaction design, layout, styling, Bevy presentation and input, accessibility, and verification of the user-facing behavior. Route by what the work changes, not by language or file extension; a Rust file can contain UI or underlying logic.

GPT-6.1-Sol is the default implementation coordinator. For mixed features, assign Opus ownership of the UI portion and Sol ownership of server, protocol, pure state logic, and integration. Agree the shared data shape and interface first, give concurrent workers separate file ownership, then review and verify the complete feature. If UI and logic share a file, use sequential ownership or patches instead of concurrent edits.

For UI-only work, an Opus parent selected by the user can lead directly; otherwise the existing coordinator delegates to an Opus UI lead. The project policy does not switch the current conversation's provider or launch a new top-level thread. An Opus UI lead can delegate separate underlying logic to Sol. Read the relevant client documentation and use the observed running UI; keep rules authoritative on the server, Bevy limited to presentation and input, and human/AI controller parity intact as required by `AGENTS.md`.

Difficult underlying work can still use the strongest/judgment role when warranted. This does not move routine implementation or all work on a mixed feature to Opus, and never authorizes Astra automatically.

For small, simple non-UI tasks, the bulk-worker role takes precedence over generic feature, refactoring, bug-fix, or swarm defaults. Delegate a bounded brief to GLM with exact file ownership and acceptance checks. Examples include local mechanical renames, a known one-function correction, and a small batch of repetitive edits within an agreed scope. Broad migrations, architectural choices, unknown-cause debugging, concurrency changes, and shared protocol or permission changes require Sol coordination or the judgment role. If a GLM task reveals that complexity, have it report the finding and hand the broader work back to the coordinator rather than expand its scope. UI work still belongs to Opus, including small UI changes; a separate simple non-UI portion can be delegated to GLM.

## Reasoning budgets

Read `.agents/pstack-effort.json` for the project budget, model baselines, and role-specific overrides. The project budget is `session`, with the user-selected model baselines below. These baselines apply to delegated tasks through any provider exposing the exact model ID. Effort selection does not change the parent conversation's model or provider settings.

| Model | Baseline effort |
| --- | --- |
| GLM 5.3, glm-5-3 | max |
| GPT-6.1-Sol, gpt-6.1-sol | high |
| Claude Opus 5.5, claude-opus-5-5 | high |
| Grok 4.7, grok-4.7 | high |

Grok remains high while the user is undecided about xhigh. Do not promote it automatically. Store exact model baselines in `modelEfforts`, exact role-wide overrides in `roleEfforts`, and role/model pairs in `roleModelEfforts`. Models without a saved baseline use the project budget.

| Setup choice | Budget value | Requested effort |
| --- | --- | --- |
| Keep model baselines / current settings | session | Saved role/model baseline; otherwise no override |
| unlimited — keep max | unlimited | Preserve saved role/model baselines; otherwise max, or xhigh for Grok |
| large — xhigh reasoning | large | xhigh |
| medium — high reasoning | medium | high |
| small — medium reasoning | small | medium |

Unlimited preserves configured role/model baselines as the original setup preserves customized defaults. Where no baseline is configured, it uses the original max/xhigh pattern. It does not select `ultra`, `ultrathink`, or `ultracode`. It is a reasoning preset, not an unlimited spending or execution budget, and it never authorizes Astra automatically.

At dispatch time, run `.agents/scripts/pstack-effort.ts` against the refreshed catalog and resolved provider/model. Pass its validated `options` into T3's `delegate_task` target, or the equivalent native tool fields when supported. The target provider can expose `reasoningEffort`, `reasoning_effort`, `effort`, `reasoning`, or a discrete `thinking` option. Boolean thinking toggles and permission options are not reasoning levels.

For budget presets, use the highest supported standard effort at or below the requested level, following `max > xhigh > high > medium > low`. Report any reduction. For example, Mistral Vibe's GLM 5.3 has no xhigh value, so the large preset resolves to `thinking: high`. The advertised `extra-high` spelling is equivalent to xhigh, but pass the provider's actual spelling. If no appropriate level is advertised, report that the target needs a choice; do not dispatch with invented options.

Resolve effort in this order: exact task effort, task-specific budget, role/model override, role-wide override, model baseline, saved project budget. A task-specific unlimited budget preserves the most specific saved baseline; other task presets replace that baseline with their requested ceiling. Exact efforts and saved baselines must be supported by the selected model, otherwise report that a choice is needed. An explicit `session` override omits effort options. Do not enable fast mode or change service tiers as part of effort selection.

Task-specific requests such as "use the small budget for this task" override the project budget for that workflow without changing the saved JSON. Save project-wide budget changes only when requested. A per-role override is recorded under the exact role label in `roleEfforts`.

When no saved baseline or exact override applies, the session preset lets same-provider child tasks inherit effort when the runtime supports it. Cross-provider tasks then keep the target provider's current or default setting. The live catalog does not universally expose the parent session's effort, so equivalent effort across providers is not guaranteed without an explicit supported level.

The existing difficulty routing remains in effect: ordinary work uses its normal role, and the hardest work uses the strongest selection. Budget presets apply to the resulting model. This does not introduce an automatic effort increase beyond the selected preset.

Keep each provider's configured permission and approval options. Provider-specific options such as Mistral's `mode` can leave a child task waiting for approval. Report that state without automatically changing the option or weakening permissions.

## Outside T3 Code

Use the current runtime's native discovery and delegation tools and verified model IDs. Keep the Sol implementation and Opus UI/judgment preferences when the native runtime can express them. Otherwise non-UI roles can fall back to `inherit-parent`, with reduced panel diversity reported. UI work still requires an available Opus route or an explicit user-selected alternative; do not silently route it to Sol because cross-provider tools are absent. Continue independent non-UI work while reporting the unavailable UI role. Do not pass T3 provider IDs to a native CLI.

Invoke `poteto-mode` explicitly for a task. Automatic plugin routing is not enabled by this setup.

## Last setup resolution

Refreshed from T3's live catalog on 2026-10-04 for this project. This is an informational snapshot, not a pinned allowlist. Resolve again before a workflow starts. Codex, Claude, Cursor, and Mistral Vibe are eligible for child tasks. The dedicated Grok provider is disabled; Grok 4.7 is available through Cursor.

GLM 5.3 is also verified as a panel alternative through Mistral Vibe: provider `acpRegistry_mistral_vibe`, model `glm-5-3`. Its advertised reasoning option is `thinking`; the saved baseline is max. Its provider approval mode is currently `accept-edits`, which remains unchanged.

| P-Stack role | Resolved provider | Resolved model |
| --- | --- | --- |
| feature, refactoring | codex | gpt-6.1-sol |
| UI design, implementation, interaction, and visual verification | claudeAgent | claude-opus-5-5 |
| small changes and bounded mechanical work | acpRegistry_mistral_vibe | glm-5-3 |
| bug-fix | claudeAgent | claude-opus-5-5 |
| perf-issue | claudeAgent | claude-opus-5-5 |
| hillclimb | claudeAgent | claude-opus-5-5 |
| judgment and prose | claudeAgent | claude-opus-5-5 |
| strongest judgment / hardest tasks | claudeAgent | claude-opus-5-5 |
| how explorer | codex | gpt-6.1-sol |
| how explainer | claudeAgent | claude-opus-5-5 |
| why investigators | codex | gpt-6.1-sol |
| why synthesizer | claudeAgent | claude-opus-5-5 |
| reflect tooling | codex | gpt-6.1-sol |
| reflect judgment, divergent, synthesizer | claudeAgent | claude-opus-5-5 |
| swarm workers | codex | gpt-6.1-sol |
| arena runners, arena cross-judge pool, architect runners, interrogate reviewers | codex + claudeAgent + cursor | gpt-6.1-sol + claude-opus-5-5 + grok-4.7 |

The saved budget is `session`, with GLM max and GPT-6.1-Sol, Opus 5.5, and Grok 4.7 high baselines in `pstack-effort.json`. Resolve effort against the live catalog with the helper before dispatch. The snapshot routes expose `reasoningEffort` on Codex, `effort` on Claude Opus, and `reasoning_effort` on Cursor Grok 4.7. Existing fast-mode, service-tier, context-window, and approval settings remain unchanged.
