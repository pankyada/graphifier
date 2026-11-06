"use client";

import { useSyncExternalStore } from "react";

/** What the pointer is previewing on the canvas: a node's lineage, or every node of a kind. */
export type Highlight = { type: "node"; id: string } | { type: "kind"; kind: string } | null;

// Hover changes on every pointer move. It lives outside the workspace context so
// that only the canvas re-renders, not every panel reading workspace state.
let current: Highlight = null;
const listeners = new Set<() => void>();

export function setHighlight(next: Highlight): void {
  if (current === next) return;
  current = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useHighlight(): Highlight {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
}
