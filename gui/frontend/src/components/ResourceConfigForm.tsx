import { useState, useEffect } from "react";
import { useResourceConfig } from "@/hooks/queries/use-resource-config";
import { useProjectResourceConfig } from "@/hooks/queries/use-project-resources";
import { useResources } from "@/hooks/queries/use-registry";
import { useSaveResourceConfig } from "@/hooks/mutations/use-registry";
import { useSaveProjectResourceConfig } from "@/hooks/mutations/use-project-resources";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Eye, EyeOff, Save } from "lucide-react";
import { toast } from "sonner";

interface Props {
  resourceType: string;
  resourceName: string;
  enabled: boolean;
  projectId?: number;
}

export default function ResourceConfigForm({
  resourceType,
  resourceName,
  enabled,
  projectId,
}: Props) {
  const globalConfig = useResourceConfig(
    resourceType,
    resourceName,
    { enabled: enabled && !projectId },
  );
  const projectConfig = useProjectResourceConfig(
    projectId ?? 0,
    resourceType,
    resourceName,
    { enabled: enabled && !!projectId },
  );
  const { data: config, isLoading } = projectId ? projectConfig : globalConfig;

  const globalSave = useSaveResourceConfig();
  const projectSave = useSaveProjectResourceConfig(projectId ?? 0);
  const save = projectId ? projectSave : globalSave;
  const { data: agents } = useResources("agents", {
    enabled: enabled && resourceType === "roles",
  });

  const [envState, setEnvState] = useState<Record<string, string>>({});
  const [paramsState, setParamsState] = useState<Record<string, unknown>>({});
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (config) {
      setEnvState({ ...config.env_values });
      setParamsState({ ...config.params_values });
    }
  }, [config]);

  if (isLoading || !config) return null;

  const envKeys = Object.keys(config.env_schema);
  const paramKeys = Object.keys(config.params_schema);
  if (envKeys.length === 0 && paramKeys.length === 0) return null;

  const toggleVisible = (key: string) =>
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const agentNames = (agents ?? []).map((a) => a.name);
  const defaultAgentValue = String(paramsState["default_agent"] ?? "").trim();
  const defaultAgentError =
    resourceType === "roles" &&
    defaultAgentValue &&
    agentNames.length > 0 &&
    !agentNames.includes(defaultAgentValue)
      ? "Agent not found in installed agents"
      : "";

  const handleSave = () => {
    save.mutate(
      {
        type: resourceType,
        name: resourceName,
        env_values: envKeys.length > 0 ? envState : undefined,
        params_values: paramKeys.length > 0 ? paramsState : undefined,
      },
      {
        onSuccess: () => toast.success("Configuration saved"),
        onError: () => toast.error("Failed to save configuration"),
      },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {envKeys.length > 0 && (
        <>
          <Separator />
          <div className="flex flex-col gap-3">
            <h4 className="text-sm font-semibold">Environment Variables</h4>
            {envKeys.map((key) => {
              const schema = config.env_schema[key];
              const isVisible = visibleKeys.has(key);
              return (
                <div key={key} className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <Label className="text-xs font-mono">{key}</Label>
                    {schema.required && (
                      <Badge
                        variant="outline"
                        className="h-4 px-1 text-[10px] text-red-500 border-red-200"
                      >
                        required
                      </Badge>
                    )}
                  </div>
                  {schema.description && (
                    <p className="text-xs text-muted-foreground">
                      {schema.description}
                    </p>
                  )}
                  <div className="relative">
                    <Input
                      type={isVisible ? "text" : "password"}
                      value={envState[key] ?? ""}
                      onChange={(e) =>
                        setEnvState((prev) => ({
                          ...prev,
                          [key]: e.target.value,
                        }))
                      }
                      placeholder={key}
                      className="h-8 pr-8 text-xs font-mono"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      onClick={() => toggleVisible(key)}
                    >
                      {isVisible ? (
                        <EyeOff className="h-3.5 w-3.5" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {paramKeys.length > 0 && (
        <>
          <Separator />
          <div className="flex flex-col gap-3">
            <h4 className="text-sm font-semibold">Parameters</h4>
            {paramKeys.map((key) => {
              const schema = config.params_schema[key];
              const value = paramsState[key];
              const defaultVal = schema.default;

              if (schema.type === "boolean") {
                return (
                  <div key={key} className="flex flex-col gap-1">
                    <Label className="text-xs font-mono">{key}</Label>
                    {schema.description && (
                      <p className="text-xs text-muted-foreground">
                        {schema.description}
                      </p>
                    )}
                    <Select
                      value={
                        value != null
                          ? String(value)
                          : defaultVal != null
                            ? String(defaultVal)
                            : ""
                      }
                      onValueChange={(v) =>
                        setParamsState((prev) => ({
                          ...prev,
                          [key]: v === "true",
                        }))
                      }
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true">true</SelectItem>
                        <SelectItem value="false">false</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                );
              }

              const inputType =
                schema.type === "int" || schema.type === "float"
                  ? "number"
                  : "text";
              const step = schema.type === "float" ? "any" : undefined;
              const suggestions =
                key === "default_agent" && agents
                  ? agents.map((a) => a.name)
                  : undefined;
              const listId = suggestions ? `datalist-${key}` : undefined;

              return (
                <div key={key} className="flex flex-col gap-1">
                  <Label className="text-xs font-mono">{key}</Label>
                  {schema.description && (
                    <p className="text-xs text-muted-foreground">
                      {schema.description}
                    </p>
                  )}
                  <Input
                    type={inputType}
                    step={step}
                    list={listId}
                    value={value != null ? String(value) : ""}
                    onChange={(e) =>
                      setParamsState((prev) => ({
                        ...prev,
                        [key]:
                          inputType === "number" && e.target.value !== ""
                            ? Number(e.target.value)
                            : e.target.value,
                      }))
                    }
                    placeholder={
                      defaultVal != null ? String(defaultVal) : undefined
                    }
                    className="h-8 text-xs font-mono"
                  />
                  {suggestions && (
                    <datalist id={listId}>
                      {suggestions.map((s) => (
                        <option key={s} value={s} />
                      ))}
                    </datalist>
                  )}
                  {key === "default_agent" && defaultAgentError && (
                    <p className="text-xs text-destructive">{defaultAgentError}</p>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      <Button
        size="sm"
        onClick={handleSave}
        disabled={save.isPending || !!defaultAgentError}
        className="self-start"
      >
        <Save className="mr-2 h-3.5 w-3.5" />
        {save.isPending ? "Saving..." : "Save Configuration"}
      </Button>
    </div>
  );
}
