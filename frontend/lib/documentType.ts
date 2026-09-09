export function normalizeDocumentType(value: unknown): string | null {
  if (Array.isArray(value)) {
    const values = value.filter((entry): entry is string => typeof entry === "string")
      .map((entry) => entry.trim())
      .filter(Boolean);
    return values.length > 0 ? values.join(", ") : null;
  }
  if (typeof value === "string" && value.trim()) return value.trim();
  return null;
}
