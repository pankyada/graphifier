import type { Job } from "./types";

export const ACTIVE_STATUSES = new Set(["queued", "running"]);

export function isActive(job: Pick<Job, "status">): boolean {
  return ACTIVE_STATUSES.has(job.status);
}

export type AnalysisMode = "static" | "agent";

/** Mode the job was queued with, as persisted by the API (`job.use_agent`). */
export function analysisModeOf(job: Pick<Job, "use_agent">): AnalysisMode {
  return job.use_agent ? "agent" : "static";
}

export const JOB_MODE_LABEL: Record<AnalysisMode, string> = {
  static: "Static",
  agent: "Luna",
};
