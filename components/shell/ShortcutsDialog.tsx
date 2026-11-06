"use client";

import { Dialog } from "./Dialog";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

const GROUPS: { title: string; keys: [string[], string][] }[] = [
  {
    title: "Find",
    keys: [
      [["⌘", "K"], "Search nodes and actions"],
      [["/"], "Search nodes and actions"],
    ],
  },
  {
    title: "Walk the graph",
    keys: [
      [["←", "→"], "Move to upstream or downstream neighbor"],
      [["↑", "↓"], "Move within the column"],
      [["f"], "Fit graph to view"],
    ],
  },
  {
    title: "Trace the selected node",
    keys: [
      [["u"], "Trace upstream"],
      [["d"], "Trace downstream"],
      [["b"], "Trace both directions"],
      [["⌫"], "Back to the previous focus"],
      [["Esc"], "Clear focus, then selection"],
    ],
  },
  {
    title: "Panels",
    keys: [
      [["["], "Toggle left panel"],
      [["]"], "Toggle inspector"],
      [["?"], "Show this list"],
    ],
  },
];

export function ShortcutsDialog() {
  const ws = useWorkspace();
  return (
    <Dialog open={ws.dialog === "shortcuts"} onClose={ws.closeDialog} title="Keyboard shortcuts" size="narrow">
      {GROUPS.map((group) => (
        <section key={group.title} aria-label={group.title} className="shortcut-group">
          <div className="label">{group.title}</div>
          {group.keys.map(([keys, text]) => (
            <div key={`${keys.join("+")}|${text}`} className="shortcut-row">
              <span>{text}</span>
              <span className="shortcut-keys">
                {keys.map((key) => (
                  <span key={key} className="kbd">
                    {key}
                  </span>
                ))}
              </span>
            </div>
          ))}
        </section>
      ))}
    </Dialog>
  );
}
