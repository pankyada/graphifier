"use client";

import type { ReactNode } from "react";

interface StatusLineProps {
  text: ReactNode;
  tone?: "neutral" | "bad";
}

/** Single-line status used inside rails and cards. Text carries meaning, not colour alone. */
export function StatusLine({ text, tone = "neutral" }: StatusLineProps) {
  return (
    <div
      className="empty-row"
      role={tone === "bad" ? "alert" : "status"}
      style={tone === "bad" ? { color: "var(--red-700)" } : undefined}
    >
      {text}
    </div>
  );
}
