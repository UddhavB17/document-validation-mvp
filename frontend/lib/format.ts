// Small display-only formatters shared by tables, metrics, and review panels.

export function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function formatSeconds(value: unknown): string {
  if (typeof value !== "number") {
    return "-";
  }
  return `${value.toFixed(2)}s`;
}
