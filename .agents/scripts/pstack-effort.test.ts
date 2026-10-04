import { describe, expect, test } from "bun:test";
import { resolveEffort } from "./pstack-effort";

const select = (id: string, values: string[]) => ({ type: "select", id, label: id, options: values.map((id) => ({ id, label: id })) });
const provider = (id: string, model: string, options: unknown[], child = true, cross = true) => ({
  providerInstanceId: id, canRunChildTask: child, canRunCrossProviderChildTask: cross,
  models: [{ id: model, options }],
});
const catalog = {
  inheritedProviderInstanceId: "codex",
  providers: [
    provider("codex", "gpt-6.1-sol", [select("reasoningEffort", ["low", "medium", "high", "xhigh", "max", "ultra"]), select("serviceTier", ["priority"])]),
    provider("claudeAgent", "claude-opus-5-5", [select("effort", ["low", "medium", "high", "max"])]),
    provider("cursor", "grok-4.7", [select("reasoning_effort", ["low", "medium", "high", "xhigh"]), { id: "fast", type: "boolean", currentValue: true }]),
    provider("cursor-alias", "grok-4.7", [select("reasoning", ["low", "medium", "high", "extra-high"])]),
    provider("acpRegistry_mistral_vibe", "glm-5-3", [select("thinking", ["low", "medium", "high", "max"]), select("mode", ["ask", "accept-edits", "auto-approve"])]),
  ],
};
const config = { schemaVersion: 1, budget: "session", roleEfforts: {} };
const defaults = { catalog, config, providerInstanceId: "codex", model: "gpt-6.1-sol", role: "feature" };
const baselines = {
  ...config,
  modelEfforts: { "glm-5-3": "max", "gpt-6.1-sol": "high", "claude-opus-5-5": "high", "grok-4.7": "high" },
};

describe("P-Stack effort resolution", () => {
  test("session inherits settings by emitting no options", () => {
    expect(resolveEffort(defaults)).toEqual({ status: "ready", providerInstanceId: "codex", model: "gpt-6.1-sol", role: "feature", budget: "session", options: [], requestedEffort: null, effectiveEffort: null, adjustment: null });
    expect(resolveEffort({ ...defaults, config: baselines, budget: "session" })).toMatchObject({ status: "ready", effectiveEffort: "high" });
    expect(resolveEffort({ ...defaults, config: baselines, budget: "session", effort: "session" })).toMatchObject({ status: "ready", options: [] });
    expect(resolveEffort({ ...defaults, config: { schemaVersion: 1, budget: "session" } })).toMatchObject({ status: "ready", options: [] });
  });

  test("presets use each provider's advertised option and leave other options untouched", () => {
    for (const [providerInstanceId, model, id] of [
      ["codex", "gpt-6.1-sol", "reasoningEffort"],
      ["claudeAgent", "claude-opus-5-5", "effort"],
      ["cursor", "grok-4.7", "reasoning_effort"],
      ["acpRegistry_mistral_vibe", "glm-5-3", "thinking"],
    ]) {
      if (providerInstanceId === undefined || model === undefined || id === undefined) throw new Error("Incomplete fixture");
      expect(resolveEffort({ ...defaults, providerInstanceId, model, budget: "medium" })).toMatchObject({ status: "ready", options: [{ id, value: "high" }], requestedEffort: "high", effectiveEffort: "high", adjustment: null });
    }
  });

  test("large lowers to high when Mistral has max but no xhigh", () => {
    expect(resolveEffort({ ...defaults, providerInstanceId: "acpRegistry_mistral_vibe", model: "glm-5-3", budget: "large" })).toMatchObject({ status: "ready", options: [{ id: "thinking", value: "high" }], requestedEffort: "xhigh", effectiveEffort: "high", adjustment: "Lowered xhigh to supported high" });
  });

  test("unlimited falls back to original max/xhigh baselines without escalating to ultra", () => {
    expect(resolveEffort({ ...defaults, budget: "unlimited" })).toMatchObject({ status: "ready", effectiveEffort: "max" });
    expect(resolveEffort({ ...defaults, providerInstanceId: "cursor", model: "grok-4.7", budget: "unlimited" })).toMatchObject({ status: "ready", effectiveEffort: "xhigh" });
  });

  test("extra-high aliases normalize but dispatch retains the advertised value", () => {
    expect(resolveEffort({ ...defaults, providerInstanceId: "cursor-alias", model: "grok-4.7", effort: "xhigh" })).toMatchObject({ status: "ready", options: [{ id: "reasoning", value: "extra-high" }], effectiveEffort: "xhigh" });
    expect(resolveEffort({ ...defaults, effort: "extra-high" })).toMatchObject({ status: "ready", options: [{ id: "reasoningEffort", value: "xhigh" }] });
  });

  test("explicit unsupported effort never silently lowers or accepts ultra", () => {
    expect(resolveEffort({ ...defaults, providerInstanceId: "claudeAgent", model: "claude-opus-5-5", effort: "xhigh" })).toMatchObject({ status: "needs-choice" });
    expect(resolveEffort({ ...defaults, effort: "ultra" })).toMatchObject({ status: "needs-choice" });
    expect(resolveEffort({ ...defaults, providerInstanceId: "claudeAgent", model: "claude-opus-5-5", config: { ...config, roleEfforts: { feature: "xhigh" } } })).toMatchObject({ status: "needs-choice" });
  });

  test("model baselines apply across roles and unlimited preserves configured high", () => {
    expect(resolveEffort({ ...defaults, config: baselines })).toMatchObject({ status: "ready", effectiveEffort: "high" });
    expect(resolveEffort({ ...defaults, config: baselines, role: "investigator" })).toMatchObject({ status: "ready", effectiveEffort: "high" });
    for (const [providerInstanceId, model] of [["cursor", "grok-4.7"], ["claudeAgent", "claude-opus-5-5"]]) {
      if (providerInstanceId === undefined || model === undefined) throw new Error("Incomplete fixture");
      expect(resolveEffort({ ...defaults, config: baselines, providerInstanceId, model, budget: "unlimited" })).toMatchObject({ status: "ready", effectiveEffort: "high" });
    }
  });

  test("role-model then role override model defaults; task effort beats task budget", () => {
    const config = { ...baselines, roleEfforts: { feature: "low" }, roleModelEfforts: { feature: { "glm-5-3": "high" } } };
    expect(resolveEffort({ ...defaults, config })).toMatchObject({ status: "ready", effectiveEffort: "low" });
    const glm = { ...defaults, config, providerInstanceId: "acpRegistry_mistral_vibe", model: "glm-5-3" };
    expect(resolveEffort(glm)).toMatchObject({ status: "ready", effectiveEffort: "high" });
    expect(resolveEffort({ ...glm, role: "other" })).toMatchObject({ status: "ready", effectiveEffort: "max" });
    expect(resolveEffort({ ...glm, budget: "small" })).toMatchObject({ status: "ready", effectiveEffort: "medium" });
    expect(resolveEffort({ ...glm, budget: "small", effort: "max" })).toMatchObject({ status: "ready", effectiveEffort: "max" });
    expect(resolveEffort({ ...glm, effort: "session" })).toMatchObject({ status: "ready", options: [] });
  });

  test("small task override replaces GLM's stored max baseline", () => {
    expect(resolveEffort({ ...defaults, config: baselines, providerInstanceId: "acpRegistry_mistral_vibe", model: "glm-5-3", budget: "small" })).toMatchObject({ status: "ready", effectiveEffort: "medium" });
  });

  test("boolean thinking is not an effort setting, and duplicate select options need a choice", () => {
    for (const options of [
      [{ id: "thinking", type: "boolean", currentValue: true }],
      [select("thinking", ["high"]), select("effort", ["high"])],
    ]) {
      const catalog = { inheritedProviderInstanceId: "codex", providers: [provider("codex", "gpt-6.1-sol", options)] };
      expect(resolveEffort({ ...defaults, catalog, budget: "medium" })).toMatchObject({ status: "needs-choice" });
      expect(resolveEffort({ ...defaults, catalog })).toMatchObject({ status: "ready", options: [] });
    }
  });

  test("disabled providers, cross-provider restrictions, and stale routes need a choice", () => {
    expect(resolveEffort({ ...defaults, model: "stale" })).toMatchObject({ status: "needs-choice" });
    expect(resolveEffort({ ...defaults, providerInstanceId: "stale" })).toMatchObject({ status: "needs-choice" });
    for (const [child, cross] of [[false, true], [true, false]]) {
      const catalog = { inheritedProviderInstanceId: "parent", providers: [provider("codex", "gpt-6.1-sol", [], child, cross)] };
      expect(resolveEffort({ ...defaults, catalog })).toMatchObject({ status: "needs-choice" });
    }
  });

  test("malformed JSON shapes fail at the boundary", () => {
    expect(() => resolveEffort({ ...defaults, catalog: { providers: "bad" } })).toThrow();
    expect(() => resolveEffort({ ...defaults, config: { ...config, modelEfforts: { model: true } } })).toThrow();
    expect(() => resolveEffort({ ...defaults, budget: "fast" })).toThrow();
  });

  test("CLI reads only local JSON and reports invalid input with nonzero exit", async () => {
    const prefix = `/tmp/pstack-effort-${crypto.randomUUID()}`;
    const catalogPath = `${prefix}-catalog.json`;
    const configPath = `${prefix}-config.json`;
    try {
      await Bun.write(catalogPath, JSON.stringify(catalog));
      await Bun.write(configPath, JSON.stringify(baselines));
      const args = [process.execPath, `${import.meta.dir}/pstack-effort.ts`, "--catalog", catalogPath, "--config", configPath, "--provider", "codex", "--model", "gpt-6.1-sol", "--role", "feature"];
      const child = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" });
      expect(await child.exited).toBe(0);
      expect(JSON.parse(await new Response(child.stdout).text())).toMatchObject({ status: "ready", effectiveEffort: "high" });
      await Bun.write(catalogPath, "{invalid");
      const invalid = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" });
      expect(await invalid.exited).toBe(1);
      expect(JSON.parse(await new Response(invalid.stderr).text())).toMatchObject({ status: "error" });
      expect(await new Response(invalid.stdout).text()).toBe("");
    } finally {
      await Bun.file(catalogPath).delete();
      await Bun.file(configPath).delete();
    }
  });
});
