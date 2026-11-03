"use client";

import { Ban, CircleAlert, CircleCheckBig, CircleDashed } from "lucide-react";

const LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const KNOWN = new Set(Object.keys(LABELS));

/** Job status chip. Always shows text and an icon, never colour alone. */
export function StatusChip({ status, cancelling = false }: { status: string; cancelling?: boolean }) {
  const key = KNOWN.has(status) ? status : "queued";
  const label = cancelling ? "Cancelling…" : (LABELS[status] ?? status);
  const Icon = key === "completed" ? CircleCheckBig : key === "failed" ? CircleAlert : key === "cancelled" ? Ban : key === "running" ? null : CircleDashed;
  return (
    <span className={`chip ${cancelling ? "running" : key}`}>
      {Icon ? <Icon className="icon" aria-hidden="true" /> : <span className="spinner-dot" aria-hidden="true" />}
      <span className="chip-text">{label}</span>
    </span>
  );
}
