"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, isAbortError, messageOf } from "@/lib/api";
import type { AgentApiMode, ReasoningEffort, AgentSettings, AgentSettingsInput, AgentConnectionTest } from "@/lib/types";
import { RefreshCw } from "lucide-react";
import { Dialog } from "./Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

/** Endpoint credentials are write-only and kept in form memory until submission. */
export function SettingsDialog() {
  const ws = useWorkspace();
  const open = ws.dialog === "settings";
  return (
    <Dialog open={open} onClose={ws.closeDialog} title="Settings" size="default">
      {open ? <SettingsBody /> : null}
    </Dialog>
  );
}

function yesNo(value: boolean | undefined): string {
  if (value === undefined) return "—";
  return value ? "yes" : "no";
}

function SettingsBody() {
  const ws = useWorkspace();
  const settings = ws.settings.data;
  const sync = ws.lastSync;

  return (
    <div className="stack">
      {ws.settings.error ? (
        <p className="error-text" role="alert">
          Settings unavailable: {ws.settings.error}
        </p>
      ) : null}
      {ws.settings.loading && !settings ? <p className="muted" style={{ margin: 0 }}>Loading settings…</p> : null}

      {settings ? <AgentSettingsForm key={JSON.stringify(settings.agent)} initial={settings.agent} /> : null}

      {settings ? (
        <div className="settings-grid" aria-label="Sanitized runtime settings">
          <div>
            <span className="k">Repository root</span>
            <span className="v">{settings.repo_root}</span>
          </div>
          <div>
            <span className="k">System identity</span>
            <span className="v">{settings.system}</span>
          </div>
          <div>
            <span className="k">Environment (this view)</span>
            <span className="v">{ws.environment}</span>
          </div>
          <div>
            <span className="k">Neo4j configured</span>
            <span className="v">{yesNo(settings.neo4j.enabled)}</span>
          </div>
          <div>
            <span className="k">API token required</span>
            <span className="v">{yesNo(settings.api_token_required)}</span>
          </div>
        </div>
      ) : null}

      <p className="hint" style={{ margin: 0 }}>
        API keys are submitted to the server and never returned in settings. The browser keeps an entered key only while this form is open.
      </p>

      <div className="label">Last Neo4j sync (this session)</div>
      {sync ? (
        <div className="settings-grid">
          <div>
            <span className="k">Status</span>
            <span className="v">{sync.status}</span>
          </div>
          <div>
            <span className="k">Projection</span>
            <span className="v">
              {sync.projection_id} · {sync.nodes} nodes · {sync.edges} edges
            </span>
          </div>
          {sync.error ? (
            <div>
              <span className="k">Error</span>
              <span className="v" style={{ color: "var(--red-700)" }}>
                {sync.error}
              </span>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          No sync run in this session. There is no sync-status endpoint, so nothing is shown as synced.
        </p>
      )}

      <div className="row-inline">
        <button type="button" className="btn small" onClick={ws.settings.reload}>
          <RefreshCw className="icon" aria-hidden="true" />
          Reload settings
        </button>
      </div>
    </div>
  );
}

const SPLASH = {
  base_url: "http://192.168.1.176:8000/v1",
  model: "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M",
  api_mode: "chat_completions" as const,
};

function AgentSettingsForm({ initial }: { initial: AgentSettings }) {
  const ws = useWorkspace();
  const [baseUrl, setBaseUrl] = useState(initial.base_url ?? "https://api.openai.com/v1");
  const [model, setModel] = useState(initial.model);
  const [apiMode, setApiMode] = useState<AgentApiMode>(initial.api_mode ?? initial.api ?? "responses");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort | "">(initial.reasoning_effort ?? "");
  const [hierarchyModel, setHierarchyModel] = useState(initial.hierarchy_model ?? initial.model);
  const [hierarchyEffort, setHierarchyEffort] = useState<ReasoningEffort | "">(initial.hierarchy_reasoning_effort ?? "");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<AgentConnectionTest | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  function invalidateTest() {
    setTestResult(null);
    setError(null);
  }

  function presetSplash() {
    setBaseUrl(SPLASH.base_url);
    setModel(SPLASH.model);
    setHierarchyModel(SPLASH.model);
    setHierarchyEffort("");
    setApiMode(SPLASH.api_mode);
    setReasoningEffort("");
    setApiKey("");
    setClearKey(true);
    invalidateTest();
  }

  function presetOpenAI() {
    setBaseUrl("https://api.openai.com/v1"); setApiMode("responses");
    setModel("gpt-6-luna"); setReasoningEffort("low");
    setHierarchyModel("gpt-6-luna"); setHierarchyEffort("high");
    invalidateTest();
  }

  function payload(): AgentSettingsInput {
    return {
      base_url: baseUrl.trim(),
      model: model.trim(),
      api_mode: apiMode,
      reasoning_effort: reasoningEffort || null,
      hierarchy_model: hierarchyModel.trim(),
      hierarchy_reasoning_effort: hierarchyEffort || null,
      api_key: clearKey ? undefined : apiKey || undefined,
      clear_api_key: clearKey,
    };
  }

  async function run(action: "save" | "test") {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(action);
    setError(null);
    try {
      if (action === "test") {
        setTestResult(null);
        const result = await api.testAgentConnection(payload(), controller.signal);
        if (!controller.signal.aborted) setTestResult(result);
      } else {
        await api.saveAgentSettings(payload(), controller.signal);
        if (!controller.signal.aborted) {
          setApiKey("");
          setClearKey(false);
          ws.settings.reload();
          ws.toast("ok", "AI endpoint settings saved.");
        }
      }
    } catch (failure) {
      if (!isAbortError(failure)) setError(messageOf(failure));
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run("save");
  }

  const advertisedModel = testResult?.models.includes(model.trim());

  return (
    <form onSubmit={save} aria-label="AI endpoint settings" className="stack">
      <fieldset disabled={busy !== null} className="stack" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <legend className="label">Shared AI endpoint</legend>
        <div className="row-inline">
          <button type="button" className="btn small" onClick={presetOpenAI}>Use OpenAI defaults</button>
          <button type="button" className="btn small" onClick={presetSplash}>Use Splash preset</button>
          <span className="hint">Local endpoint · Chat Completions · no API key</span>
        </div>
        <label className="field">
          <span className="label">Base URL</span>
          <input
            className="input"
            type="url"
            required
            value={baseUrl}
            placeholder="http://localhost:8000/v1"
            onChange={(event) => { setBaseUrl(event.target.value); invalidateTest(); }}
          />
        </label>
        <label className="field">
          <span className="label">API format</span>
          <select className="input" value={apiMode} onChange={(event) => { setApiMode(event.target.value as AgentApiMode); invalidateTest(); }}>
            <option value="chat_completions">Chat Completions (OpenAI compatible)</option>
            <option value="responses">Responses API</option>
          </select>
        </label>
        <datalist id="endpoint-models">{testResult?.models.map((id) => <option key={id} value={id} />)}</datalist>
        <WorkflowModel title="Extraction harness" description="Investigates source and resolves extraction gaps." model={model} effort={reasoningEffort} onModel={setModel} onEffort={setReasoningEffort} presets={["low", "medium"]} />
        <WorkflowModel title="Architecture grouping" description="Consolidates components and explains their responsibilities." model={hierarchyModel} effort={hierarchyEffort} onModel={setHierarchyModel} onEffort={setHierarchyEffort} presets={["high"]} />
        <label className="field">
          <span className="label">API key (optional)</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={apiKey}
            disabled={clearKey}
            placeholder={initial.api_key_configured ? "Leave blank to keep the saved key" : "No key configured"}
            onChange={(event) => { setApiKey(event.target.value); invalidateTest(); }}
          />
        </label>
        <label className="check-consent">
          <input
            type="checkbox"
            checked={clearKey}
            onChange={(event) => { setClearKey(event.target.checked); setApiKey(""); invalidateTest(); }}
          />
          <span>Use no API key (clear the saved key)</span>
        </label>
        <div className="row-inline" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" disabled={!baseUrl.trim()} onClick={() => void run("test")}>
            {busy === "test" ? "Testing…" : "Test connection"}
          </button>
          <button type="submit" className="btn primary" disabled={!baseUrl.trim() || !model.trim() || !hierarchyModel.trim()}>
            {busy === "save" ? "Saving…" : "Save endpoint"}
          </button>
        </div>
      </fieldset>
      <p className="hint" style={{ margin: 0 }}>Test connection fetches the model list from this endpoint using the entered settings. Save applies the configuration to the API and worker.</p>
      {testResult ? (
        <p className={advertisedModel ? "note-line" : "hint"} role="status">
          Endpoint returned {testResult.models.length} model{testResult.models.length === 1 ? "" : "s"}.
          Harness: {advertisedModel ? "listed" : "not listed"}. Architecture: {testResult.models.includes(hierarchyModel.trim()) ? "listed" : "not listed"}. Listing does not verify reasoning-effort support.
        </p>
      ) : null}
      {error ? <p className="error-text" role="alert">{error}</p> : null}
    </form>
  );
}

function WorkflowModel({ title, description, model, effort, onModel, onEffort, presets }: {
  title: string; description: string; model: string; effort: ReasoningEffort | "";
  onModel: (value: string) => void; onEffort: (value: ReasoningEffort | "") => void; presets: ReasoningEffort[];
}) {
  return <fieldset className="stack" style={{ border: "1px solid var(--border)", padding: 14, borderRadius: 12, minWidth: 0 }}>
    <legend className="label">{title}</legend><p className="hint" style={{ margin: 0 }}>{description}</p>
    <div className="row-inline">{presets.map((preset) => <button type="button" className="btn small" key={preset} onClick={() => { onModel("gpt-6-luna"); onEffort(preset); }}>Luna {preset}</button>)}</div>
    <label className="field"><span className="label">{title} model</span><input className="input" list="endpoint-models" required value={model} onChange={(event) => onModel(event.target.value)} /></label>
    <label className="field"><span className="label">{title} reasoning effort</span><select className="input" value={effort} onChange={(event) => onEffort(event.target.value as ReasoningEffort | "")}><option value="">Provider default</option>{["none", "minimal", "low", "medium", "high", "xhigh"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
    <p className="hint" style={{ margin: 0 }}>Choose an advertised model or enter a custom ID. Use provider default if reasoning effort is unsupported.</p>
  </fieldset>;
}
