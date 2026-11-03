"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Workspace } from "./useWorkspace";

const WorkspaceContext = createContext<Workspace | null>(null);

export function WorkspaceProvider({ value, children }: { value: Workspace; children: ReactNode }) {
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}
