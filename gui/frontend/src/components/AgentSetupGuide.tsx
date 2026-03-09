import { useAgentValidation } from "@/hooks/queries/use-registry";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, KeyRound, Terminal } from "lucide-react";

interface Props {
  agentName: string;
}

export default function AgentSetupGuide({ agentName }: Props) {
  const { data } = useAgentValidation(agentName);

  if (!data) return null;

  const hasIssues = !data.tools_ok || data.setup_command || !data.env_ok;
  if (!hasIssues) return null;

  return (
    <div className="mb-4 space-y-3">
      {!data.tools_ok && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Missing Prerequisites</AlertTitle>
          <AlertDescription>
            {data.missing_tools.map((t) => (
              <div key={t.name} className="mt-1">
                <strong>{t.name}</strong> not found on PATH.
                {t.install_hint && (
                  <code className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs">
                    {t.install_hint}
                  </code>
                )}
              </div>
            ))}
          </AlertDescription>
        </Alert>
      )}

      {data.setup_command && (
        <Alert>
          <Terminal className="h-4 w-4" />
          <AlertTitle>Setup</AlertTitle>
          <AlertDescription>
            <p>
              {data.setup_description ||
                "Run initial authentication in your terminal:"}
            </p>
            <code className="mt-1 block rounded bg-muted px-2 py-1 text-xs">
              {data.setup_command}
            </code>
            <p className="mt-2 text-muted-foreground">
              Or set the API key in the config below instead.
            </p>
          </AlertDescription>
        </Alert>
      )}

      {!data.env_ok && !data.setup_command && data.missing_env.length > 0 && (
        <Alert>
          <KeyRound className="h-4 w-4" />
          <AlertTitle>API Key Required</AlertTitle>
          <AlertDescription>
            <p>
              Set{" "}
              {data.missing_env.map((v, i) => (
                <span key={v}>
                  {i > 0 && ", "}
                  <code className="rounded bg-muted px-1 py-0.5 text-xs">{v}</code>
                </span>
              ))}{" "}
              in the config below to authenticate.
            </p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
