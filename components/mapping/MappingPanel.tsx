"use client";

import { useState, type FormEvent } from "react";
import { Undo2, Eye, RotateCcw } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { ACTOR, type Workspace } from "@/components/workspace/useWorkspace";
import { EvidenceList, type ViewerTarget } from "@/components/evidence/EvidenceList";
import { api, ApiError, messageOf } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Resolution, SymbolEntry } from "@/lib/types";
import { ConflictList, PreviewPanel } from "./PreviewPanel";

interface MappingPanelProps {
  onOpenEvidence: (target: ViewerTarget) => void;
  /** Raw expression of the selected node, used to suggest referenced unresolved symbols. */
  selectedExpression: string | null;
}

/**
 * Mapping tab. Proposals never change the graph. Apply is gated on the
 * expected version and on no live conflict. Actor is always "human".
 */
export function MappingPanel({ onOpenEvidence, selectedExpression }: MappingPanelProps) {
  const ws = useWorkspace();

  if (ws.scope === "all" || !ws.repoId) {
    return (
      <p className="muted" style={{ margin: 0 }}>
        Mappings belong to one repository. Pick a repository, then choose an unresolved symbol.
      </p>
    );
  }
  if (ws.symbols.loading && !ws.symbols.data) return <p className="muted" style={{ margin: 0 }}>Loading symbols…</p>;
  if (ws.symbols.error && !ws.symbols.data) {
    return (
      <p className="error-text" role="alert">
        Symbols unavailable: {ws.symbols.error}
      </p>
    );
  }

  const symbol = ws.symbols.data?.symbols.find((item) => item.name === ws.mappingSymbol) ?? null;
  const resolution = ws.mappingResolutionId
    ? (ws.resolutions.data?.resolutions.find((item) => item.id === ws.mappingResolutionId) ?? null)
    : null;

  if (!ws.mappingSymbol && !resolution) {
    const suggestions = selectedExpression
      ? (ws.symbols.data?.symbols ?? []).filter((item) => !item.resolved && selectedExpression.includes(item.name))
      : [];
    return (
      <div className="stack">
        <p className="muted" style={{ margin: 0 }}>
          Pick an unresolved symbol in the Mappings section of the left rail.
        </p>
        {suggestions.map((item) => (
          <button key={`${item.name}|${item.expression}`} type="button" className="btn small" onClick={() => ws.openMapping(item.name, null)}>
            Map referenced symbol {item.name}
          </button>
        ))}
      </div>
    );
  }

  const name = ws.mappingSymbol ?? resolution?.symbol ?? "";
  return (
    <MappingDetail
      key={`${name}|${resolution?.id ?? ""}`}
      name={name}
      symbol={symbol}
      resolution={resolution}
      onOpenEvidence={onOpenEvidence}
      ws={ws}
    />
  );
}

interface MappingDetailProps {
  name: string;
  symbol: SymbolEntry | null;
  resolution: Resolution | null;
  onOpenEvidence: (target: ViewerTarget) => void;
  ws: Workspace;
}

function MappingDetail({ name, symbol, resolution, onOpenEvidence, ws }: MappingDetailProps) {
  const repoId = ws.repoId ?? "";
  const environment = ws.environment;
  const applied: Resolution | null =
    resolution?.status === "applied" ? resolution : (symbol?.resolution ?? null);

  const [expression, setExpression] = useState(resolution?.status === "proposed" ? resolution.expression : "");
  const [defaultValue, setDefaultValue] = useState(symbol?.default_value ?? "");
  const [proposal, setProposal] = useState<Resolution | null>(resolution?.status === "proposed" ? resolution : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [confirmRetract, setConfirmRetract] = useState(false);

  const conflicts: Resolution[] = proposal?.preview?.conflicts?.length
    ? proposal.preview.conflicts
    : proposal?.conflict
      ? [proposal.conflict]
      : [];
  const canApply = !!proposal && proposal.status === "proposed" && !!proposal.preview && conflicts.length === 0 && !busy;

  const applyBlockReason = !proposal
    ? "Propose a value expression first."
    : proposal.status !== "proposed"
      ? `This proposal is ${proposal.status}.`
      : !proposal.preview
        ? "Load the preview before applying."
        : conflicts.length > 0
          ? "Resolve the conflict first: a live binding already exists for this symbol in this environment."
          : "";

  const loadPreview = async (id: string) => {
    const result = await api.resolutionPreview(id);
    setProposal({ ...result.resolution, preview: result.preview });
    return result;
  };

  const propose = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!expression.trim()) {
      setError("Expression is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setStale(null);
    try {
      const created = await api.proposeResolution({
        repoId,
        environment,
        symbol: name,
        expression: expression.trim(),
        defaultValue: defaultValue.trim() || undefined,
        actor: ACTOR,
      });
      setProposal(created);
      ws.toast("info", "Proposal created. Review the preview before applying. The graph has not changed.");
      ws.reloadMappings();
    } catch (err) {
      ws.fail("Propose failed", err);
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      await loadPreview(proposal.id);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    setStale(null);
    try {
      const updated = await api.applyResolution(proposal.id, proposal.version, ACTOR);
      ws.toast("ok", `Binding applied to ${name}. Graph reloaded.`);
      setProposal(null);
      ws.reloadAfterBinding();
      ws.reloadMappings();
      ws.openMapping(name, updated.id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Version or conflict changed under us: refresh the preview and make the user re-confirm.
        setStale(`${messageOf(err)}. The preview was refreshed. Review it, then apply again.`);
        try {
          await loadPreview(proposal.id);
        } catch (refreshErr) {
          setError(messageOf(refreshErr));
        }
      } else {
        setError(messageOf(err));
        ws.fail("Apply failed", err);
      }
    } finally {
      setBusy(false);
    }
  };

  const retract = async (target: Resolution) => {
    setBusy(true);
    setError(null);
    try {
      await api.retractResolution(target.id, target.version, ACTOR);
      ws.toast("ok", `Retracted ${target.symbol}. Graph reloaded.`);
      setConfirmRetract(false);
      ws.reloadAfterBinding();
      ws.reloadMappings();
      ws.openMapping(name, null);
    } catch (err) {
      setError(messageOf(err));
      ws.reloadMappings();
    } finally {
      setBusy(false);
    }
  };

  const stateLabel = applied ? "applied" : proposal ? proposal.status : symbol?.resolved ? "resolved" : "unresolved";

  return (
    <div className="stack">
      <div className="row-inline">
        <span className="mono" style={{ fontWeight: 600, fontSize: 13 }}>
          {name}
        </span>
        <span className={`chip ${stateLabel}`}>{stateLabel}</span>
        <span className="chip tag">{environment}</span>
      </div>

      {symbol ? (
        <>
          <div className="label">Raw expression (never executed)</div>
          <pre className="raw-block">{symbol.expression}</pre>
          <div className="row-inline" style={{ fontSize: 12 }}>
            <span className="muted">Default value</span>
            <span className="mono">{symbol.default_value ?? "—"}</span>
          </div>
          <div className="label">Evidence</div>
          <EvidenceList
            items={symbol.evidence ? [symbol.evidence] : []}
            fallbackRepoId={repoId}
            active={null}
            onOpen={onOpenEvidence}
          />
        </>
      ) : (
        <p className="hint" style={{ margin: 0 }}>
          This symbol is not in the latest completed analysis. Run analysis again if sources changed.
        </p>
      )}

      {applied ? (
        <div className="result-card applied" aria-label="Applied binding">
          <div className="row-inline" style={{ justifyContent: "space-between" }}>
            <span className="chip applied">applied</span>
            <span className="note-line">
              v{applied.version}
              {applied.actor ? ` · ${applied.actor}` : ""} · {relativeTime(applied.updated_at)}
            </span>
          </div>
          <pre className="raw-block" style={{ margin: 0 }}>
            {applied.expression}
          </pre>
          {confirmRetract ? (
            <div className="row-inline" role="group" aria-label="Confirm retract">
              <span className="note-line">Retract this binding? The graph will drop it.</span>
              <button type="button" className="btn danger small" disabled={busy} onClick={() => void retract(applied)}>
                <Undo2 className="icon" aria-hidden="true" />
                Retract
              </button>
              <button type="button" className="btn small" onClick={() => setConfirmRetract(false)}>
                Keep
              </button>
            </div>
          ) : (
            <div>
              <button type="button" className="btn danger small" disabled={busy} onClick={() => setConfirmRetract(true)}>
                <Undo2 className="icon" aria-hidden="true" />
                Retract
              </button>
            </div>
          )}
        </div>
      ) : null}

      {!applied ? (
        <form onSubmit={propose} className="stack" aria-label="Propose a value expression">
          <div className="field">
            <label className="label" htmlFor="mapping-expression">
              Value expression
            </label>
            <textarea
              id="mapping-expression"
              className="textarea mono"
              rows={2}
              required
              value={expression}
              onChange={(event) => setExpression(event.target.value)}
              placeholder="e.g. prod_lake.customer_scores"
              spellCheck={false}
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="mapping-default">
              Default value (optional)
            </label>
            <input
              id="mapping-default"
              className="input mono"
              value={defaultValue}
              onChange={(event) => setDefaultValue(event.target.value)}
              spellCheck={false}
            />
          </div>
          <div className="row-inline" style={{ justifyContent: "space-between" }}>
            <span className="hint">Actor recorded as “{ACTOR}”. Proposals do not change the graph.</span>
            <button type="submit" className="btn primary small" disabled={busy || !expression.trim()}>
              Propose
            </button>
          </div>
        </form>
      ) : null}

      {proposal ? (
        <div className="result-card" aria-label="Proposal">
          <div className="row-inline" style={{ justifyContent: "space-between" }}>
            <span className={`chip ${proposal.status}`}>{proposal.status}</span>
            <span className="note-line">expected version {proposal.version}</span>
          </div>
          <pre className="raw-block" style={{ margin: 0 }}>
            {proposal.expression}
          </pre>

          {proposal.preview ? (
            <PreviewPanel preview={proposal.preview} onOpenEvidence={onOpenEvidence} />
          ) : (
            <p className="hint" style={{ margin: 0 }}>
              No preview loaded yet.
            </p>
          )}

          <ConflictList conflicts={conflicts} />

          {stale ? (
            <p className="error-text" role="status">
              {stale}
            </p>
          ) : null}
          {error ? (
            <p className="error-text" role="alert">
              {error}
            </p>
          ) : null}

          <div className="row-inline">
            <button type="button" className="btn small" disabled={busy} onClick={() => void refresh()}>
              <RotateCcw className="icon" aria-hidden="true" />
              {proposal.preview ? "Refresh preview" : "Load preview"}
            </button>
            <span className="grow" />
            <button
              type="button"
              className="btn primary small"
              disabled={!canApply}
              aria-describedby={applyBlockReason ? "apply-block-reason" : undefined}
              onClick={() => void apply()}
            >
              <Eye className="icon" aria-hidden="true" />
              Apply v{proposal.version}
            </button>
          </div>
          {applyBlockReason ? (
            <p id="apply-block-reason" className="hint" style={{ margin: 0 }}>
              {applyBlockReason}
            </p>
          ) : null}
        </div>
      ) : null}

      {!proposal && error ? (
        <p className="error-text" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
