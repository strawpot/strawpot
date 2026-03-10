import { useState, useEffect } from "react";
import { useResources } from "@/hooks/queries/use-registry";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Save } from "lucide-react";

interface ConfigFormProps {
  values: Record<string, unknown>;
  placeholders?: Record<string, unknown>;
  onSave: (data: Record<string, unknown>) => void;
  saving?: boolean;
}

// --- helpers to flatten / unflatten nested TOML ---

interface FlatState {
  runtime: string;
  isolation: string;
  memory: string;
  orchestrator_role: string;
  orchestrator_permission_mode: string;
  policy_max_depth: string;
  policy_agent_timeout: string;
  policy_max_delegate_retries: string;
  policy_cache_delegations: string;
  policy_cache_max_entries: string;
  policy_cache_ttl_seconds: string;
  policy_max_num_delegations: string;
  session_merge_strategy: string;
  session_pull_before_session: string;
  session_pr_command: string;
  trace_enabled: string;
}

function toFlat(v: Record<string, unknown>): FlatState {
  const orch = (v.orchestrator ?? {}) as Record<string, unknown>;
  const policy = (v.policy ?? {}) as Record<string, unknown>;
  const session = (v.session ?? {}) as Record<string, unknown>;
  const trace = (v.trace ?? {}) as Record<string, unknown>;
  return {
    runtime: str(v.runtime),
    isolation: str(v.isolation),
    memory: str(v.memory),
    orchestrator_role: str(orch.role),
    orchestrator_permission_mode: str(orch.permission_mode),
    policy_max_depth: str(policy.max_depth),
    policy_agent_timeout: str(policy.agent_timeout),
    policy_max_delegate_retries: str(policy.max_delegate_retries),
    policy_cache_delegations: str(policy.cache_delegations),
    policy_cache_max_entries: str(policy.cache_max_entries),
    policy_cache_ttl_seconds: str(policy.cache_ttl_seconds),
    policy_max_num_delegations: str(policy.max_num_delegations),
    session_merge_strategy: str(session.merge_strategy),
    session_pull_before_session: str(session.pull_before_session),
    session_pr_command: str(session.pr_command),
    trace_enabled: str(trace.enabled),
  };
}

function str(v: unknown): string {
  if (v == null) return "";
  return String(v);
}

function toNested(flat: FlatState): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  if (flat.runtime) result.runtime = flat.runtime;
  if (flat.isolation) result.isolation = flat.isolation;
  if (flat.memory) result.memory = flat.memory;

  const orch: Record<string, unknown> = {};
  if (flat.orchestrator_role) orch.role = flat.orchestrator_role;
  if (flat.orchestrator_permission_mode)
    orch.permission_mode = flat.orchestrator_permission_mode;
  if (Object.keys(orch).length > 0) result.orchestrator = orch;

  const policy: Record<string, unknown> = {};
  if (flat.policy_max_depth)
    policy.max_depth = Number(flat.policy_max_depth);
  if (flat.policy_agent_timeout)
    policy.agent_timeout = Number(flat.policy_agent_timeout);
  if (flat.policy_max_delegate_retries)
    policy.max_delegate_retries = Number(flat.policy_max_delegate_retries);
  if (flat.policy_cache_delegations)
    policy.cache_delegations = flat.policy_cache_delegations === "true";
  if (flat.policy_cache_max_entries)
    policy.cache_max_entries = Number(flat.policy_cache_max_entries);
  if (flat.policy_cache_ttl_seconds)
    policy.cache_ttl_seconds = Number(flat.policy_cache_ttl_seconds);
  if (flat.policy_max_num_delegations)
    policy.max_num_delegations = Number(flat.policy_max_num_delegations);
  if (Object.keys(policy).length > 0) result.policy = policy;

  const session: Record<string, unknown> = {};
  if (flat.session_merge_strategy)
    session.merge_strategy = flat.session_merge_strategy;
  if (flat.session_pull_before_session)
    session.pull_before_session = flat.session_pull_before_session;
  if (flat.session_pr_command) session.pr_command = flat.session_pr_command;
  if (Object.keys(session).length > 0) result.session = session;

  const trace: Record<string, unknown> = {};
  if (flat.trace_enabled) trace.enabled = flat.trace_enabled === "true";
  if (Object.keys(trace).length > 0) result.trace = trace;

  return result;
}

// --- select field options ---

const ISOLATION_OPTIONS = ["none", "worktree"];
const PERMISSION_OPTIONS = ["default", "plan", "bypassPermissions"];
const MERGE_OPTIONS = ["auto", "local", "pr"];
const PULL_OPTIONS = ["prompt", "always", "never"];
const BOOL_OPTIONS = ["true", "false"];

// placeholder value for shadcn Select "empty" option
const EMPTY = "__empty__";

export default function ConfigForm({
  values,
  placeholders,
  onSave,
  saving,
}: ConfigFormProps) {
  const [state, setState] = useState<FlatState>(toFlat(values));
  const { data: agents } = useResources("agents");
  const { data: roles } = useResources("roles");
  const { data: memories } = useResources("memories");

  const ph = placeholders ? toFlat(placeholders) : undefined;

  // Compare by content, not reference, so stale React Query cache hits still sync
  const valuesKey = JSON.stringify(values);
  useEffect(() => {
    setState(toFlat(values));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valuesKey]);

  const set = (key: keyof FlatState) => (val: string) =>
    setState((prev) => ({ ...prev, [key]: val }));

  const handleSave = () => {
    onSave(toNested(state));
  };

  const agentNames = (agents ?? []).map((a) => a.name);
  const roleNames = (roles ?? []).map((r) => r.name);
  const memoryNames = new Set((memories ?? []).map((m) => m.name));
  memoryNames.add("none");
  const memoryOptions = [...memoryNames].sort();

  const runtimeError =
    state.runtime && agentNames.length > 0 && !agentNames.includes(state.runtime)
      ? "Runtime not found in installed agents"
      : "";
  const roleError =
    state.orchestrator_role && roleNames.length > 0 && !roleNames.includes(state.orchestrator_role)
      ? "Role not found in installed roles"
      : "";
  const memoryError =
    state.memory && !memoryOptions.includes(state.memory)
      ? "Memory not found in installed providers"
      : "";
  const hasValidationError = !!runtimeError || !!roleError || !!memoryError;

  return (
    <div className="flex flex-col gap-6">
      {/* General */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">General</h3>
        <Separator />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Runtime">
            <Input
              list="cfg-dl-runtime"
              value={state.runtime}
              onChange={(e) => set("runtime")(e.target.value)}
              placeholder={ph?.runtime || "strawpot-claude-code"}
              className="h-8 text-xs"
            />
            {agentNames.length > 0 && (
              <datalist id="cfg-dl-runtime">
                {agentNames.map((n) => (
                  <option key={n} value={n} />
                ))}
              </datalist>
            )}
            {runtimeError && (
              <p className="text-xs text-destructive">{runtimeError}</p>
            )}
          </Field>
          <Field label="Isolation">
            <SelectField
              value={state.isolation}
              onChange={set("isolation")}
              options={ISOLATION_OPTIONS}
              placeholder={ph?.isolation || "none"}
              allowEmpty
            />
          </Field>
          <Field label="Memory">
            <Input
              list="cfg-dl-memory"
              value={state.memory}
              onChange={(e) => set("memory")(e.target.value)}
              placeholder={ph?.memory || "dial"}
              className="h-8 text-xs"
            />
            <datalist id="cfg-dl-memory">
              {memoryOptions.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
            {memoryError && (
              <p className="text-xs text-destructive">{memoryError}</p>
            )}
          </Field>
        </div>
      </section>

      {/* Orchestrator */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Orchestrator</h3>
        <Separator />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Role">
            <Input
              list="cfg-dl-role"
              value={state.orchestrator_role}
              onChange={(e) => set("orchestrator_role")(e.target.value)}
              placeholder={ph?.orchestrator_role || "ai-ceo"}
              className="h-8 text-xs"
            />
            {roleNames.length > 0 && (
              <datalist id="cfg-dl-role">
                {roleNames.map((n) => (
                  <option key={n} value={n} />
                ))}
              </datalist>
            )}
            {roleError && (
              <p className="text-xs text-destructive">{roleError}</p>
            )}
          </Field>
          <Field label="Permission Mode">
            <SelectField
              value={state.orchestrator_permission_mode}
              onChange={set("orchestrator_permission_mode")}
              options={PERMISSION_OPTIONS}
              placeholder={ph?.orchestrator_permission_mode || "default"}
              allowEmpty
            />
          </Field>
        </div>
      </section>

      {/* Policy */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Policy</h3>
        <Separator />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Max Depth">
            <Input
              type="number"
              value={state.policy_max_depth}
              onChange={(e) => set("policy_max_depth")(e.target.value)}
              placeholder={ph?.policy_max_depth || "3"}
              className="h-8 text-xs"
            />
          </Field>
          <Field label="Agent Timeout (seconds)">
            <Input
              type="number"
              value={state.policy_agent_timeout}
              onChange={(e) => set("policy_agent_timeout")(e.target.value)}
              placeholder={ph?.policy_agent_timeout || "none"}
              className="h-8 text-xs"
            />
          </Field>
          <Field label="Max Delegate Retries">
            <Input
              type="number"
              value={state.policy_max_delegate_retries}
              onChange={(e) =>
                set("policy_max_delegate_retries")(e.target.value)
              }
              placeholder={ph?.policy_max_delegate_retries || "0"}
              className="h-8 text-xs"
            />
          </Field>
          <Field label="Cache Delegations">
            <SelectField
              value={state.policy_cache_delegations}
              onChange={set("policy_cache_delegations")}
              options={BOOL_OPTIONS}
              placeholder={ph?.policy_cache_delegations === "false" ? "false" : "true"}
              allowEmpty
            />
          </Field>
          <Field label="Cache Max Entries">
            <Input
              value={state.policy_cache_max_entries}
              onChange={(e) =>
                set("policy_cache_max_entries")(e.target.value)
              }
              placeholder={ph?.policy_cache_max_entries || "0 (unlimited)"}
              className="h-8 text-xs"
            />
          </Field>
          <Field label="Cache TTL (seconds)">
            <Input
              value={state.policy_cache_ttl_seconds}
              onChange={(e) =>
                set("policy_cache_ttl_seconds")(e.target.value)
              }
              placeholder={ph?.policy_cache_ttl_seconds || "0 (unlimited)"}
              className="h-8 text-xs"
            />
          </Field>
          <Field label="Max Delegations">
            <Input
              type="number"
              min="0"
              value={state.policy_max_num_delegations}
              onChange={(e) =>
                set("policy_max_num_delegations")(e.target.value)
              }
              placeholder={ph?.policy_max_num_delegations || "0 (unlimited)"}
              className="h-8 text-xs"
            />
          </Field>
        </div>
      </section>

      {/* Session */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Session</h3>
        <Separator />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Merge Strategy">
            <SelectField
              value={state.session_merge_strategy}
              onChange={set("session_merge_strategy")}
              options={MERGE_OPTIONS}
              placeholder={ph?.session_merge_strategy || "auto"}
              allowEmpty
            />
          </Field>
          <Field label="Pull Before Session">
            <SelectField
              value={state.session_pull_before_session}
              onChange={set("session_pull_before_session")}
              options={PULL_OPTIONS}
              placeholder={ph?.session_pull_before_session || "prompt"}
              allowEmpty
            />
          </Field>
          <Field label="PR Command" className="sm:col-span-3">
            <Input
              value={state.session_pr_command}
              onChange={(e) => set("session_pr_command")(e.target.value)}
              placeholder={
                ph?.session_pr_command ||
                "gh pr create --base {base_branch} --head {session_branch}"
              }
              className="h-8 text-xs font-mono"
            />
          </Field>
        </div>
      </section>

      {/* Trace */}
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Trace</h3>
        <Separator />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Enabled">
            <SelectField
              value={state.trace_enabled}
              onChange={set("trace_enabled")}
              options={BOOL_OPTIONS}
              placeholder={ph?.trace_enabled || "true"}
              allowEmpty
            />
          </Field>
        </div>
      </section>

      <Button
        size="sm"
        onClick={handleSave}
        disabled={saving || hasValidationError}
        className="self-start"
      >
        <Save className="mr-2 h-3.5 w-3.5" />
        {saving ? "Saving..." : "Save Configuration"}
      </Button>
    </div>
  );
}

// --- small helper components ---

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-1 ${className ?? ""}`}>
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}

function SelectField({
  value,
  onChange,
  options,
  placeholder,
  allowEmpty,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
  allowEmpty?: boolean;
}) {
  return (
    <Select
      value={value || (allowEmpty ? EMPTY : "")}
      onValueChange={(v) => onChange(v === EMPTY ? "" : v)}
    >
      <SelectTrigger className="h-8 text-xs">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {allowEmpty && (
          <SelectItem value={EMPTY} className="text-muted-foreground">
            {placeholder ? `Default (${placeholder})` : "Default"}
          </SelectItem>
        )}
        {options.map((opt) => (
          <SelectItem key={opt} value={opt}>
            {opt}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
