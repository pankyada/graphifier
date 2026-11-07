import type { Job, RepositoryImport } from "./types";

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
  agent: "AI",
};

export function isImportActive(job: Pick<RepositoryImport, "status">): boolean {
  return job.status === "queued" || job.status === "cloning";
}

/** Scope checks prevent a run in another repository or environment blocking this one. */
export function activeAnalysisJob(jobs: Job[], repoId: string | null, environment: string): Job | undefined {
  return jobs.find((job) => job.repo_id === repoId && job.environment === environment && isActive(job));
}

/** Describe the job the API actually returned, including a deduplicated opposite-mode run. */
export function analysisSubmissionMessage(job: Job, repoName: string, requestedMode: AnalysisMode, requestedEmbeddings: boolean, knownJob: boolean): string {
  const mode = analysisModeOf(job);
  const existing = knownJob || mode !== requestedMode || !!job.use_embeddings !== requestedEmbeddings || job.status !== "queued";
  const label = mode === "agent" ? "AI" : job.use_ai_hierarchy ? "Static + AI grouping" : "Static";
  return `${existing ? "Existing " : ""}${label} analysis is ${job.status} for ${repoName} (${job.environment}).`;
}

/** Only the server can establish whether a saved checkpoint is safe to resume. */
export function canResumeJob(job: Pick<Job, "status" | "resumable">): boolean {
  return job.resumable === true && ["failed", "cancelled", "interrupted"].includes(job.status);
}
