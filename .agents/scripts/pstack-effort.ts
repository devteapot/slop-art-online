export type Budget = "session" | "unlimited" | "large" | "medium" | "small";
export type Effort = "session" | "low" | "medium" | "high" | "xhigh" | "max";
type ExplicitEffort = Exclude<Effort, "session">;
type Config = {
  budget: Budget;
  roleEfforts: ReadonlyMap<string, Effort>;
  modelEfforts: ReadonlyMap<string, Effort>;
  roleModelEfforts: ReadonlyMap<string, ReadonlyMap<string, Effort>>;
};
type SelectOption = { id: string; values: string[] };
type Model = { id: string; effortOptions: SelectOption[] };
type Provider = {
  id: string;
  canRunChildTask: boolean;
  canRunCrossProviderChildTask: boolean;
  models: Model[];
};
type Catalog = { inheritedProviderInstanceId: string; providers: Provider[] };
type Context = { providerInstanceId: string; model: string; role: string; budget: Budget };
export type Resolution =
  | (Context & {
      status: "ready";
      options: { id: string; value: string }[];
      requestedEffort: ExplicitEffort | null;
      effectiveEffort: ExplicitEffort | null;
      adjustment: string | null;
    })
  | (Context & { status: "needs-choice"; reason: string });

const effortIds = new Set(["reasoningEffort", "reasoning_effort", "effort", "reasoning", "thinking"]);
const ladder: readonly ExplicitEffort[] = ["low", "medium", "high", "xhigh", "max"];

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function list(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a nonempty string`);
  return value;
}

function flag(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} must be a boolean`);
  return value;
}

function budget(value: unknown): Budget {
  switch (value) {
    case "session": case "unlimited": case "large": case "medium": case "small": return value;
    default: throw new Error("Budget must be session, unlimited, large, medium, or small");
  }
}

function effort(value: unknown): Effort | null {
  switch (value) {
    case "session": case "low": case "medium": case "high": case "xhigh": case "max": return value;
    case "extra-high": return "xhigh";
    default: return null;
  }
}

function parseEfforts(value: unknown, label: string): ReadonlyMap<string, Effort> {
  const result = new Map<string, Effort>();
  for (const [role, level] of Object.entries(record(value, label))) {
    const parsed = effort(level);
    if (parsed === null || role.trim() === "") throw new Error(`Invalid effort for ${label}.${role}`);
    result.set(role, parsed);
  }
  return result;
}

function parseConfig(value: unknown): Config {
  const input = record(value, "Config");
  if (input.schemaVersion !== 1) throw new Error("Config schemaVersion must be 1");
  const roleModelEfforts = new Map<string, ReadonlyMap<string, Effort>>();
  for (const [role, models] of Object.entries(record(input.roleModelEfforts === undefined ? {} : input.roleModelEfforts, "roleModelEfforts"))) {
    if (role.trim() === "") throw new Error("roleModelEfforts role must be nonempty");
    roleModelEfforts.set(role, parseEfforts(models, `roleModelEfforts.${role}`));
  }
  return {
    budget: budget(input.budget),
    roleEfforts: parseEfforts(input.roleEfforts === undefined ? {} : input.roleEfforts, "roleEfforts"),
    modelEfforts: parseEfforts(input.modelEfforts === undefined ? {} : input.modelEfforts, "modelEfforts"),
    roleModelEfforts,
  };
}

function parseCatalog(value: unknown): Catalog {
  const input = record(value, "Catalog");
  const providers = list(input.providers, "providers").map((item): Provider => {
    const provider = record(item, "Provider");
    const models = list(provider.models, "models").map((item): Model => {
      const model = record(item, "Model");
      const effortOptions: SelectOption[] = [];
      for (const item of model.options == null ? [] : list(model.options, "model.options")) {
        const option = record(item, "Model option");
        const id = text(option.id, "Option id");
        if (option.type === "boolean") continue;
        if (option.type !== "select") throw new Error(`Unsupported catalog option type for ${id}`);
        const values = list(option.options, "select.options").map((item) => text(record(item, "Option value").id, "Value id"));
        if (effortIds.has(id)) effortOptions.push({ id, values });
      }
      return { id: text(model.id, "Model id"), effortOptions };
    });
    return {
      id: text(provider.providerInstanceId, "Provider id"),
      canRunChildTask: flag(provider.canRunChildTask, "canRunChildTask"),
      canRunCrossProviderChildTask: flag(provider.canRunCrossProviderChildTask, "canRunCrossProviderChildTask"),
      models,
    };
  });
  return { inheritedProviderInstanceId: text(input.inheritedProviderInstanceId, "Inherited provider id"), providers };
}

function presetTarget(preset: Exclude<Budget, "session">, model: string): ExplicitEffort {
  switch (preset) {
    case "unlimited": return model.startsWith("grok-") ? "xhigh" : "max";
    case "large": return "xhigh";
    case "medium": return "high";
    case "small": return "medium";
  }
}

export function resolveEffort(input: {
  catalog: unknown;
  config: unknown;
  providerInstanceId: string;
  model: string;
  role: string;
  budget?: string;
  effort?: string;
}): Resolution {
  const catalog = parseCatalog(input.catalog);
  const config = parseConfig(input.config);
  const selectedBudget = input.budget === undefined ? config.budget : budget(input.budget);
  const context: Context = { providerInstanceId: input.providerInstanceId, model: input.model, role: input.role, budget: selectedBudget };
  const needsChoice = (reason: string): Resolution => ({ ...context, status: "needs-choice", reason });
  const providers = catalog.providers.filter((provider) => provider.id === input.providerInstanceId);
  const provider = providers[0];
  if (providers.length !== 1 || provider === undefined) return needsChoice("Provider is absent or ambiguous in the live catalog");
  if (!provider.canRunChildTask) return needsChoice("Provider cannot run child tasks");
  if (provider.id !== catalog.inheritedProviderInstanceId && !provider.canRunCrossProviderChildTask) {
    return needsChoice("Provider cannot run cross-provider child tasks");
  }
  const models = provider.models.filter((model) => model.id === input.model);
  const model = models[0];
  if (models.length !== 1 || model === undefined) return needsChoice("Model is absent or ambiguous on the selected provider");
  const baseline = config.roleModelEfforts.get(input.role)?.get(input.model)
    ?? config.roleEfforts.get(input.role) ?? config.modelEfforts.get(input.model);
  const override = input.effort !== undefined ? effort(input.effort)
    : input.budget === undefined || selectedBudget === "unlimited" || selectedBudget === "session" ? baseline
    : undefined;
  if (override === null) return needsChoice("Explicit effort must be session, low, medium, high, xhigh (or extra-high), or max");
  if (override === "session" || (override === undefined && selectedBudget === "session")) {
    return { ...context, status: "ready", options: [], requestedEffort: null, effectiveEffort: null, adjustment: null };
  }
  const requestedEffort = override ?? presetTarget(selectedBudget === "session" ? "unlimited" : selectedBudget, model.id);
  if (model.effortOptions.length !== 1) {
    return needsChoice(model.effortOptions.length === 0 ? "Model advertises no discrete effort option" : "Model advertises multiple discrete effort options; choose one explicitly");
  }
  const option = model.effortOptions[0];
  if (option === undefined) return needsChoice("Model advertises no discrete effort option");
  const supported = new Map<ExplicitEffort, string>();
  for (const value of option.values) {
    const normalized = effort(value);
    if (normalized !== null && normalized !== "session") {
      if (supported.has(normalized)) return needsChoice(`Effort option ${option.id} has ambiguous values for ${normalized}`);
      supported.set(normalized, value);
    }
  }
  let effectiveEffort: ExplicitEffort | null = null;
  if (override !== undefined) {
    if (supported.has(requestedEffort)) effectiveEffort = requestedEffort;
  } else {
    for (const level of ladder.slice(0, ladder.indexOf(requestedEffort) + 1)) {
      if (supported.has(level)) effectiveEffort = level;
    }
  }
  if (effectiveEffort === null) return needsChoice(`Effort ${requestedEffort} is unsupported by ${option.id}; supported values: ${option.values.join(", ") || "none"}`);
  const value = supported.get(effectiveEffort);
  if (value === undefined) return needsChoice("No supported effort value could be resolved");
  return {
    ...context, status: "ready", options: [{ id: option.id, value }], requestedEffort, effectiveEffort,
    adjustment: effectiveEffort === requestedEffort ? null : `Lowered ${requestedEffort} to supported ${effectiveEffort}`,
  };
}

async function main(): Promise<void> {
  const args = new Map<string, string>();
  const allowed = new Set(["--catalog", "--provider", "--model", "--role", "--config", "--budget", "--effort"]);
  for (let index = 2; index < Bun.argv.length; index += 2) {
    const key = Bun.argv[index];
    const value = Bun.argv[index + 1];
    if (key === undefined || !allowed.has(key) || value === undefined || value.startsWith("--") || args.has(key)) {
      throw new Error("Usage: bun .agents/scripts/pstack-effort.ts --catalog PATH --provider ID --model ID --role LABEL [--config PATH] [--budget PRESET] [--effort LEVEL]");
    }
    args.set(key, value);
  }
  const catalogPath = text(args.get("--catalog"), "--catalog");
  const configPath = args.get("--config") ?? ".agents/pstack-effort.json";
  const result = resolveEffort({
    catalog: await Bun.file(catalogPath).json(), config: await Bun.file(configPath).json(),
    providerInstanceId: text(args.get("--provider"), "--provider"),
    model: text(args.get("--model"), "--model"), role: text(args.get("--role"), "--role"),
    ...(args.has("--budget") ? { budget: args.get("--budget") } : {}),
    ...(args.has("--effort") ? { effort: args.get("--effort") } : {}),
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (import.meta.main) {
  try {
    await main();
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ status: "error", reason: error instanceof Error ? error.message : "Invalid input" })}\n`);
    process.exitCode = 1;
  }
}
