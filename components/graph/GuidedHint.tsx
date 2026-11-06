"use client";

import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { useHighlight } from "@/lib/highlight";
import { PREF_KEYS, readNumberPref, writePref } from "@/lib/prefs";

const STEPS: ReactNode[] = [
  "Hover a node to light up where its data comes from and goes.",
  "Click a node to read the source code behind it.",
  <>
    Double-click a node, or press <span className="kbd">B</span>, to trace only its lineage.
  </>,
  <>
    Press <span className="kbd">⌘</span> <span className="kbd">K</span> to jump to any table or action.
  </>,
];

/** First-run tips that advance when the user does the thing, and never return once finished. */
export function GuidedHint() {
  const ws = useWorkspace();
  const highlight = useHighlight();
  // Starts finished so nothing flashes before the stored step is read on the client.
  const [step, setStep] = useState(STEPS.length);

  useEffect(() => setStep(readNumberPref(PREF_KEYS.hintStep, 0)), []);

  let reached = 0;
  if (highlight?.type === "node") reached = 1;
  if (ws.selection?.kind === "node") reached = 2;
  if (ws.focus) reached = 3;
  if (ws.dialog === "palette") reached = STEPS.length;

  useEffect(() => {
    if (reached <= step) return;
    setStep(reached);
    writePref(PREF_KEYS.hintStep, reached);
  }, [reached, step]);

  if (step >= STEPS.length) return null;

  return (
    <div className="guided-hint" role="status" key={step}>
      <span className="guided-hint-steps" aria-label={`Tip ${step + 1} of ${STEPS.length}`}>
        {STEPS.map((_, index) => (
          <span key={index} className={index <= step ? "is-on" : undefined} />
        ))}
      </span>
      <span>{STEPS[step]}</span>
      <button
        type="button"
        className="icon-btn"
        aria-label="Dismiss tips"
        onClick={() => {
          setStep(STEPS.length);
          writePref(PREF_KEYS.hintStep, STEPS.length);
        }}
      >
        <X className="icon" aria-hidden="true" />
      </button>
    </div>
  );
}
