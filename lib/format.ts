export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return "";
  const tail = id.includes(":") ? id.slice(id.indexOf(":") + 1) : id;
  return tail.length > length ? tail.slice(0, length) : tail;
}

export function basename(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

/** Parent of a POSIX absolute path, or null at filesystem root. */
export function parentPath(path: string): string | null {
  const trimmed = path.replace(/\/+$/, "");
  if (!trimmed || trimmed === "/") return null;
  const index = trimmed.lastIndexOf("/");
  if (index <= 0) return "/";
  return trimmed.slice(0, index);
}

export function plural(count: number, word: string, pluralForm = `${word}s`): string {
  return `${count} ${count === 1 ? word : pluralForm}`;
}

export function titleCase(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function truncateText(value: string | null | undefined, max: number): string {
  if (!value) return "";
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export function sha8(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 8) : "";
}
