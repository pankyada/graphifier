/** Known extraction warnings that indicate a completed but incomplete AI pass. */
export function isPartialAiWarning(warning: unknown): boolean {
  const message = typeof warning === "string" ? warning : warning && typeof warning === "object" && "message" in warning ? String(warning.message) : "";
  return ["AI analysis incomplete (", "AI validation repairs exhausted;", "AI extraction discarded after two unsuccessful repairs:", "agent file limit reached; static extraction used"].some((prefix) => message.includes(prefix));
}
