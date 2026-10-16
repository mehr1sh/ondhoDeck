"use client";

/**
 * Bring-your-own-key settings for document extraction.
 *
 * Security: the API key lives only in this component's state while the user types it. It is cleared as soon as
 * the form is submitted (before the request resolves, whether it succeeds or fails), is only ever sent in a
 * request body, and is never written to storage, cookies, the URL or logs. The API never returns it; only the
 * masked `key_hint` is displayed.
 */
import { useId, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Card,
  CheckboxField,
  Dialog,
  ErrorState,
  LoadingBlock,
  Notice,
  SelectField,
  TextField,
  cx,
} from "@/components/ui";
import { CredentialStatusBadge } from "@/components/badges";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { providerLabel } from "@/lib/extraction";
import { formatDateTime } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { AIProvider, AIProvidersOut, CredentialOut, CredentialTestOut, ProviderInfo } from "@/lib/types";

export interface ResultMessage {
  tone: "success" | "warning" | "danger" | "info";
  title: string;
  message: string;
  /** Server-provided detail, shown when it adds information. */
  detail?: string;
}

const CODE_MESSAGES: Record<string, Omit<ResultMessage, "detail">> = {
  ok: { tone: "success", title: "Connection works", message: "The provider accepted the key." },
  invalid_key: {
    tone: "danger",
    title: "Invalid key",
    message: "The provider rejected this key. Check that you copied the whole key, or create a new one, then replace it.",
  },
  permission_denied: {
    tone: "danger",
    title: "Key lacks permission",
    message: "The key is not allowed to use this model or API. Check the key's permissions with the provider.",
  },
  quota_exceeded: {
    tone: "warning",
    title: "Quota exceeded",
    message:
      "The key works but the provider account has no remaining credit or quota. Add credit with the provider, then test again.",
  },
  rate_limited: {
    tone: "warning",
    title: "Rate limited",
    message: "Too many attempts in a short time. Wait a few minutes and try again.",
  },
  workspace_required: {
    tone: "warning",
    title: "Workspace ID needed",
    message:
      "This Anthropic key is not scoped to a workspace, so every request must name one. Enter the workspace ID (it starts with wrkspc_, from Settings → Workspaces in the Claude Console), save it and test again.",
  },
  model_required: {
    tone: "warning",
    title: "Choose a model",
    message:
      "This provider needs a model. Use “Load models” to list the models available to your key, or type a model name, save it and test again.",
  },
  model_not_found: {
    tone: "warning",
    title: "Model not available",
    message: "The provider does not offer this model to your key. Load the available models and pick one.",
  },
  credential_unreadable: {
    tone: "warning",
    title: "Stored key cannot be read",
    message: "The stored key can no longer be decrypted (the server key may have changed). Replace the key.",
  },
  credential_storage_unavailable: {
    tone: "danger",
    title: "Key storage is disabled",
    message: "The server has no encryption key configured, so API keys cannot be stored. Keys are never stored unencrypted.",
  },
  network_error: { tone: "warning", title: "Provider unreachable", message: "Could not reach the provider. Try again later." },
  timeout: { tone: "warning", title: "Provider timed out", message: "The provider did not respond in time. Try again later." },
  provider_unavailable: {
    tone: "warning",
    title: "Provider unavailable",
    message: "The provider is temporarily unavailable. Try again later.",
  },
};

const WORKSPACE_ID = /^wrkspc_[A-Za-z0-9]{6,58}$/;

/** Maps a provider/test result code to a user-facing message. */
export function messageForCode(code: string, serverMessage?: string | null): ResultMessage {
  const known = CODE_MESSAGES[code];
  if (!known) {
    return { tone: "danger", title: "Test failed", message: serverMessage || "The connection test failed.", detail: code };
  }
  return { ...known, detail: serverMessage && serverMessage !== known.message ? serverMessage : undefined };
}

export function messageForTest(r: CredentialTestOut): ResultMessage {
  return r.ok ? { ...CODE_MESSAGES.ok!, detail: r.message || undefined } : messageForCode(r.code, r.message);
}

export function messageForError(e: unknown): ResultMessage {
  if (e instanceof ApiError) {
    if (e.status === 429) {
      const m = messageForCode("rate_limited");
      return e.retryAfter ? { ...m, message: `${m.message} (retry in ${e.retryAfter} seconds)` } : m;
    }
    if (e.isValidation) {
      const fields = Object.values(e.fieldErrors);
      return {
        tone: "danger",
        title: "Please check the key and model",
        message: fields.length ? fields.join(" ") : e.message,
      };
    }
    if (CODE_MESSAGES[e.code]) return messageForCode(e.code, e.message);
  }
  const d = describeError(e);
  return { tone: "danger", title: d.title, message: d.message, detail: d.requestId ? `Request ID: ${d.requestId}` : undefined };
}

function ResultNotice({ result }: { result: ResultMessage | null }) {
  if (!result) return null;
  return (
    <div role={result.tone === "success" || result.tone === "info" ? "status" : "alert"}>
      <Notice tone={result.tone} title={result.title}>
        <p>{result.message}</p>
        {result.detail && <p className="mt-1 text-xs opacity-80">{result.detail}</p>}
      </Notice>
    </div>
  );
}

type Busy = "save" | "test" | "models" | "model" | "active" | "delete" | null;

export function ProviderPanel({
  info,
  credential,
  storageAvailable,
  onChanged,
}: {
  info: ProviderInfo;
  credential: CredentialOut | null;
  storageAvailable: boolean;
  onChanged: () => void | Promise<unknown>;
}) {
  const toast = useToast();
  const label = info.label || providerLabel(info.provider) || info.provider;
  const modelRequired = !info.default_model;
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(credential?.model ?? info.default_model ?? "");
  const usesWorkspace = info.provider === "anthropic";
  const [workspace, setWorkspace] = useState(credential?.workspace_id ?? "");
  const workspaceError =
    workspace.trim() && !WORKSPACE_ID.test(workspace.trim()) ? "Workspace IDs look like wrkspc_ followed by letters and digits." : undefined;
  const [activate, setActivate] = useState(true);
  const [replacing, setReplacing] = useState(false);
  const [models, setModels] = useState<string[] | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [result, setResult] = useState<ResultMessage | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const keyFieldId = useId();
  const listId = useId();

  const showKeyForm = !credential || replacing;
  const formDisabled = !storageAvailable || busy !== null;

  const handleError = (e: unknown) => {
    const m = messageForError(e);
    setResult(m);
    if (e instanceof ApiError && e.code === "credential_unreadable") setReplacing(true);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    // Take the key out of state immediately: the input is cleared whatever happens next.
    const key = apiKey.trim();
    setApiKey("");
    setResult(null);
    if (!key) {
      setResult({ tone: "danger", title: "Enter an API key", message: `Paste your ${label} API key.` });
      return;
    }
    if (key.length < 20 || /\s/.test(key)) {
      setResult({
        tone: "danger",
        title: "That does not look like a complete key",
        message: "API keys are at least 20 characters and contain no spaces. Paste the key again.",
      });
      return;
    }
    if (workspaceError) {
      setResult({ tone: "danger", title: "Check the workspace ID", message: workspaceError });
      return;
    }
    setBusy("save");
    try {
      const r = await endpoints.saveAiCredential(info.provider, {
        api_key: key,
        model: model.trim() ? model.trim() : null,
        ...(usesWorkspace ? { workspace_id: workspace.trim() || null } : {}),
        activate,
      });
      setResult(messageForTest(r));
      setReplacing(false);
      if (r.credential?.model) setModel(r.credential.model);
      await onChanged();
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setResult(null);
    try {
      const r = await endpoints.testAiCredential(info.provider);
      setResult(messageForTest(r));
      await onChanged();
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const loadModels = async () => {
    setBusy("models");
    setResult(null);
    try {
      const r = await endpoints.aiProviderModels(info.provider);
      setModels(r.models);
      if (r.models.length === 0) {
        setResult({ tone: "warning", title: "No models listed", message: "The provider returned no models for this key." });
      }
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const saveModel = async () => {
    if (!credential) return;
    if (workspaceError) {
      setResult({ tone: "danger", title: "Check the workspace ID", message: workspaceError });
      return;
    }
    setBusy("model");
    setResult(null);
    try {
      await endpoints.updateAiCredential(info.provider, {
        model: model.trim() ? model.trim() : null,
        ...(usesWorkspace ? { workspace_id: workspace.trim() || null } : {}),
      });
      setResult({ tone: "info", title: "Model saved", message: "Test the connection to check the key works with this model." });
      await onChanged();
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const setActive = async (active: boolean) => {
    setBusy("active");
    setResult(null);
    try {
      await endpoints.updateAiCredential(info.provider, { is_active: active });
      toast.success(active ? `${label} key is now used for extraction` : `${label} key deactivated`);
      await onChanged();
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      await endpoints.deleteAiCredential(info.provider);
      setConfirmDelete(false);
      setResult(null);
      setModels(null);
      toast.success(`${label} key deleted`);
      await onChanged();
    } catch (err) {
      setConfirmDelete(false);
      handleError(err);
    } finally {
      setBusy(null);
    }
  };

  const modelField = (
    <div className="space-y-2">
      <TextField
        label="Model"
        value={model}
        list={models?.length ? listId : undefined}
        required={modelRequired}
        maxLength={120}
        disabled={!storageAvailable}
        autoComplete="off"
        spellCheck={false}
        hint={
          modelRequired
            ? `${label} needs a model. Save your key, then use “Load models” or type a model name.`
            : `Defaults to ${info.default_model}. Change it if your key should use a different model.`
        }
        onChange={(e) => setModel(e.target.value)}
      />
      {usesWorkspace && (
        <TextField
          label="Workspace ID (optional)"
          value={workspace}
          maxLength={64}
          disabled={!storageAvailable}
          autoComplete="off"
          spellCheck={false}
          error={workspaceError}
          hint="Only needed when your key is not scoped to a workspace: Anthropic then requires the workspace ID (wrkspc_…) on every request. Find it under Settings → Workspaces in the Claude Console."
          onChange={(e) => setWorkspace(e.target.value)}
        />
      )}
      {models && models.length > 0 && (
        <>
          <datalist id={listId}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <SelectField
            label="Available models"
            value={models.includes(model) ? model : ""}
            disabled={!storageAvailable}
            onChange={(e) => e.target.value && setModel(e.target.value)}
            options={[{ value: "", label: "Choose a model…" }, ...models.map((m) => ({ value: m, label: m }))]}
          />
        </>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <ResultNotice result={result} />

      {credential && (
        <div className="space-y-3 rounded-md border border-slate-200 p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-600">Stored key</span>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-900" aria-label="Masked key">
              {credential.key_hint}
            </code>
            <CredentialStatusBadge status={credential.status} />
            {credential.is_active ? <Badge tone="accent">Active</Badge> : <Badge>Inactive</Badge>}
          </div>
          <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-600">Model</dt>
              <dd className="break-all">{credential.model ?? "Not set"}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Last tested</dt>
              <dd>{credential.last_tested_at ? formatDateTime(credential.last_tested_at) : "Never"}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Updated</dt>
              <dd>{formatDateTime(credential.updated_at)}</dd>
            </div>
          </dl>
          {credential.last_error && (
            <p className="text-xs text-red-800">
              Last test: {credential.last_error}
              {credential.last_error_code ? ` (${credential.last_error_code})` : ""}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={test} loading={busy === "test"} disabled={formDisabled}>
              Test connection
            </Button>
            {credential.is_active ? (
              <Button size="sm" variant="secondary" onClick={() => setActive(false)} loading={busy === "active"} disabled={formDisabled}>
                Deactivate
              </Button>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => setActive(true)} loading={busy === "active"} disabled={formDisabled}>
                Use for extraction
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setApiKey("");
                setReplacing((v) => !v);
              }}
              disabled={formDisabled}
              aria-expanded={replacing}
              aria-controls={keyFieldId}
            >
              {replacing ? "Cancel replace" : "Replace key"}
            </Button>
            <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setConfirmDelete(true)} disabled={busy !== null}>
              Delete key
            </Button>
          </div>
          {!replacing && (
            <div className="space-y-2 border-t border-slate-200 pt-3">
              {modelField}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={loadModels} loading={busy === "models"} disabled={formDisabled}>
                  Load models
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={saveModel}
                  loading={busy === "model"}
                  disabled={
                    formDisabled ||
                    ((model.trim() || null) === (credential.model ?? null) &&
                      (!usesWorkspace || (workspace.trim() || null) === (credential.workspace_id ?? null)))
                  }
                >
                  {usesWorkspace ? "Save settings" : "Save model"}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {showKeyForm && (
        <form method="post" autoComplete="off" onSubmit={save} noValidate className="space-y-3" id={keyFieldId}>
          <TextField
            label={credential ? `New ${label} API key` : `${label} API key`}
            type="password"
            name="ai-provider-key"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            data-lpignore="true"
            data-1p-ignore="true"
            required
            value={apiKey}
            disabled={!storageAvailable}
            hint="Stored encrypted on the server and never shown again. Only the last four characters are displayed."
            onChange={(e) => setApiKey(e.target.value)}
          />
          {!credential && modelField}
          <CheckboxField
            label="Use this key for document extraction"
            checked={activate}
            disabled={!storageAvailable}
            onChange={setActivate}
            hint="Only one provider key is active at a time; activating this one deactivates the other."
          />
          <Button type="submit" loading={busy === "save"} disabled={formDisabled}>
            Save &amp; test
          </Button>
        </form>
      )}

      <Dialog
        open={confirmDelete}
        title={`Delete ${label} key?`}
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy === "delete"}>
              Delete key
            </Button>
          </>
        }
      >
        <p>
          The stored {label} key ({credential?.key_hint}) is permanently deleted. Documents processed afterwards use the
          server provider if one is configured, otherwise rule-based extraction.
        </p>
      </Dialog>
    </div>
  );
}

function ExtractionOrder({ data }: { data: AIProvidersOut }) {
  const fb = data.server_fallback;
  const active = data.active_provider ? providerLabel(data.active_provider) : null;
  return (
    <div className="space-y-2 text-sm text-slate-700">
      <p>{data.extraction_order}</p>
      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div>
          <dt className="text-slate-600">Your active key</dt>
          <dd>{active ?? "None"}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Server provider</dt>
          <dd>
            {fb.configured
              ? [providerLabel(fb.provider), fb.model].filter(Boolean).join(" · ") || "Configured"
              : "Not configured (rule-based extraction is used without your key)"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function AiProviderSettings() {
  const q = useApiQuery(() => endpoints.aiProviders(), []);
  const [selected, setSelected] = useState<AIProvider | null>(null);

  if (q.loading && !q.data) return <LoadingBlock rows={4} label="Loading AI provider settings…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const data = q.data;
  const current: AIProvider | undefined =
    selected ?? data.active_provider ?? data.credentials[0]?.provider ?? data.providers[0]?.provider;
  const info = data.providers.find((p) => p.provider === current);
  const credential = data.credentials.find((c) => c.provider === current) ?? null;

  return (
    <div className="space-y-5">
      <Card title="How documents are processed">
        <ExtractionOrder data={data} />
      </Card>

      {!data.storage_available && (
        <div role="alert">
          <Notice tone="danger" title="Key storage is disabled">
            {data.storage_message ?? "API keys cannot be stored on this server."} You can still upload documents; they are
            processed with the server provider or rule-based extraction.
          </Notice>
        </div>
      )}

      <Card title="Your provider key">
        <div className="space-y-4">
          <div role="radiogroup" aria-label="Provider" className="inline-flex rounded-md border border-slate-300 p-0.5">
            {data.providers.map((p) => {
              const cred = data.credentials.find((c) => c.provider === p.provider);
              return (
                <button
                  key={p.provider}
                  type="button"
                  role="radio"
                  aria-checked={current === p.provider}
                  onClick={() => setSelected(p.provider)}
                  className={cx(
                    "rounded px-3 py-1.5 text-sm font-medium",
                    current === p.provider ? "bg-slate-800 text-white" : "text-slate-700 hover:bg-slate-100",
                  )}
                >
                  {p.label}
                  {cred?.is_active ? " · active" : cred ? " · saved" : ""}
                </button>
              );
            })}
          </div>
          {info ? (
            <ProviderPanel
              key={info.provider}
              info={info}
              credential={credential}
              storageAvailable={data.storage_available}
              onChanged={() => q.reload()}
            />
          ) : (
            <p className="text-sm text-slate-600">No providers are available.</p>
          )}
        </div>
      </Card>
    </div>
  );
}
