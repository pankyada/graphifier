"use client";

import { CircleAlert, CircleCheckBig, Info, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

export function Toasts() {
  const ws = useWorkspace();
  return (
    <div className="toasts" role="status" aria-live="polite">
      {ws.toasts.map((item) => {
        const Icon = item.tone === "ok" ? CircleCheckBig : item.tone === "bad" ? CircleAlert : Info;
        return (
          <div key={item.id} className={`toast ${item.tone}`}>
            <Icon className="icon" aria-hidden="true" />
            <span className="toast-text">{item.text}</span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Dismiss notification"
              onClick={() => ws.dismissToast(item.id)}
            >
              <X className="icon" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
