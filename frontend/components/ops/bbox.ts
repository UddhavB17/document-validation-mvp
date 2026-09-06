export type Bbox = readonly [number, number, number, number];

export interface BoxStyle {
  left: string;
  top: string;
  width: string;
  height: string;
}

function percent(value: number): string {
  const clamped = Math.min(1, Math.max(0, value));
  return `${Math.round(clamped * 10000) / 100}%`;
}

/**
 * Convert a normalized [x0, y0, x1, y1] box (0–1 page coordinates) into CSS
 * percentages for an absolutely positioned overlay div.
 */
export function bboxToStyle(bbox: Bbox): BoxStyle {
  const [x0, y0, x1, y1] = bbox;
  return {
    left: percent(x0),
    top: percent(y0),
    width: percent(Math.max(0, x1 - x0)),
    height: percent(Math.max(0, y1 - y0)),
  };
}

export type Severity = "HIGH" | "MEDIUM" | "LOW";

export function normalizeSeverity(value: string | null | undefined): Severity {
  const upper = String(value ?? "").trim().toUpperCase();
  if (upper === "HIGH" || upper === "MEDIUM" || upper === "LOW") {
    return upper;
  }
  return "LOW";
}

const SEVERITY_BOX: Record<Severity, string> = {
  HIGH: "border-severity-high",
  MEDIUM: "border-severity-medium",
  LOW: "border-severity-low",
};

const SEVERITY_PILL: Record<Severity, string> = {
  HIGH: "bg-severity-high",
  MEDIUM: "bg-severity-medium",
  LOW: "bg-severity-low",
};

/** Border token class for the evidence overlay box. */
export function severityBoxClass(value: string | null | undefined): string {
  return SEVERITY_BOX[normalizeSeverity(value)];
}

/** Solid background token class for severity dots and pills. */
export function severityPillClass(value: string | null | undefined): string {
  return SEVERITY_PILL[normalizeSeverity(value)];
}
