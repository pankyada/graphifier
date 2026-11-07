// Small, non-secret UI preferences only. Never store tokens or credentials here.

const PREFIX = "graphifier.";

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + key, value);
  } catch {
    // Storage may be disabled; preferences are optional.
  }
}

export function readPref(key: string, fallback: string): string {
  return safeGet(key) ?? fallback;
}

export function readNumberPref(key: string, fallback: number): number {
  const raw = safeGet(key);
  const parsed = raw === null ? NaN : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function writePref(key: string, value: string | number): void {
  safeSet(key, String(value));
}

export function readList(key: string): string[] {
  const raw = safeGet(key);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function writeList(key: string, value: string[]): void {
  safeSet(key, JSON.stringify(value));
}

export function readRecord(key: string): Record<string, string> {
  const raw = safeGet(key);
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === "string") out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

export function writeRecord(key: string, value: Record<string, string>): void {
  safeSet(key, JSON.stringify(value));
}

export const PREF_KEYS = {
  environment: "environment",
  recentEnvironments: "recentEnvironments",
  scope: "scope",
  repoId: "repoId",
  railWidth: "railWidth",
  inspectorWidth: "inspectorWidth",
  railPinned: "railPinned",
  hintStep: "hintStep",
  inspectorHidden: "inspectorHidden",
} as const;
