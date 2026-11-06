"use client";

import { Check, EyeOff, FolderPlus, GitBranch, ShieldCheck } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

const BENEFITS = [
  { icon: GitBranch, text: "Trace any dataset upstream and downstream, across SAS, SQL, Python and Shell." },
  { icon: ShieldCheck, text: "Open the source lines behind what was found, right next to the graph." },
  { icon: EyeOff, text: "Files are read, never run. Static analysis stays on this device." },
];

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
      <section className="welcome" aria-labelledby="onboarding-title">
        <FlowIllustration />
        <div className="welcome-body">
          <h2 id="onboarding-title" className="welcome-title">
            See where your data really comes from
          </h2>
          <ul className="welcome-benefits">
            {BENEFITS.map(({ icon: Icon, text }) => (
              <li key={text}>
                <Icon className="icon" aria-hidden="true" />
                {text}
              </li>
            ))}
          </ul>

          <ol className="welcome-steps" aria-label="Setup steps">
            {steps.map((step, index) => (
              <li key={step.label} className={step.done ? "done" : undefined}>
                <span className="step-no" aria-hidden="true">
                  {step.done ? <Check className="icon" /> : index + 1}
                </span>
                {step.label}
                <span className="sr-only">{step.done ? "Done" : "Pending"}</span>
              </li>
            ))}
          </ol>

          <button type="button" className="btn primary large" onClick={() => ws.openDialog("browse")}>
            <FolderPlus className="icon" aria-hidden="true" />
            Choose a folder
          </button>

          <p className="note-line" style={{ margin: 0 }}>
            Starts at the allowed root
            {ws.settings.data ? (
              <>
                {" "}
                <span className="mono">{ws.settings.data.repo_root}</span>
              </>
            ) : null}
            . Nothing is registered until you choose.
          </p>
        </div>
      </section>
    </div>
  );
}

/** Decorative only: shows the idea of lineage with generic labels, never data from a repository. */
function FlowIllustration() {
  const boxes = [
    { x: 16, y: 26, label: "source", color: "#2f6690" },
    { x: 16, y: 106, label: "source", color: "#2f6690" },
    { x: 176, y: 66, label: "transform", color: "#2b7a9b" },
    { x: 336, y: 26, label: "model", color: "#a8437a" },
    { x: 336, y: 106, label: "report", color: "#1f6f5c" },
  ];
  const paths = [
    "M116 44 C146 44 146 84 176 84",
    "M116 124 C146 124 146 84 176 84",
    "M276 84 C306 84 306 44 336 44",
    "M276 84 C306 84 306 124 336 124",
  ];
  return (
    <svg className="welcome-art" viewBox="0 0 452 168" aria-hidden="true">
      {paths.map((d) => (
        <g key={d}>
          <path d={d} className="welcome-art-track" />
          <path d={d} className="welcome-art-flow" />
        </g>
      ))}
      {boxes.map((box, index) => (
        <g key={`${box.label}${box.y}`} className="welcome-art-node" style={{ animationDelay: `${index * 90}ms` }}>
          <rect x={box.x} y={box.y} width="100" height="36" rx="10" />
          <circle cx={box.x + 18} cy={box.y + 18} r="6" fill={box.color} />
          <text x={box.x + 32} y={box.y + 22}>
            {box.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
