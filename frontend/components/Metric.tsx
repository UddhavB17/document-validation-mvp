import { asText } from "@/lib/format";

export function Metric({ label, value }: { label: string; value: unknown }) {
  const valStr = asText(value);
  const isNumeric = /^[0-9₹%d\s\-:.,\/+]+$/.test(valStr) && valStr !== "—";

  return (
    <article className="metric" aria-label={`${label}: ${valStr}`}>
      <div className="metric__label">{label}</div>
      <div className={`metric__value ${isNumeric ? "metric__value--numeric" : ""}`}>
        {valStr}
      </div>
    </article>
  );
}
