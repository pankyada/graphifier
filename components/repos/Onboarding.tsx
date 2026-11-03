"use client";

import { FolderPlus } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

/** Shown only when no repository is registered. Step states come from real data. */
export function Onboarding() {
  const ws = useWorkspace();
  const hasRepo = ws.repoList.length > 0;
  const completed = ws.jobList.some((job) => job.status === "completed");
  const hasNodes = (ws.graph.data?.nodes.length ?? 0) > 0;

  const steps = [
    { label: "Register a folder", done: hasRepo },
    { label: "Run analysis", done: completed },
    { label: "Explore lineage", done: hasNodes },
  ];

  return (
    <div className="center-state">
      <section className="card" aria-labelledby="onboarding-title">
        <h2 id="onboarding-title" className="card-title">
          Register a repository
        </h2>
        <p className="card-text">Pick a local folder. Graphifier reads files, never runs them.</p>

        <ol className="steps" aria-label="Setup steps">
          {steps.map((step, index) => (
            <li key={step.label} className={step.done ? "done" : undefined}>
              <span className="step-no" aria-hidden="true">
                {step.done ? "✓" : index + 1}
              </span>
              <span>{step.label}</span>
              <span className="muted" style={{ fontSize: 11 }}>
                {step.done ? "Done" : "Pending"}
              </span>
            </li>
          ))}
        </ol>

        <div className="row-inline">
          <button type="button" className="btn primary" onClick={() => ws.openDialog("browse")}>
            <FolderPlus className="icon" aria-hidden="true" />
            Browse folders
          </button>
        </div>

        <p className="note-line" style={{ margin: 0 }}>
          The browser starts at the allowed root
          {ws.settings.data ? (
            <>
              {" "}
              <span className="mono">{ws.settings.data.repo_root}</span>
            </>
          ) : null}
          . Sample code folders under it can be registered the same way. Nothing is registered until you choose.
        </p>
      </section>
    </div>
  );
}
