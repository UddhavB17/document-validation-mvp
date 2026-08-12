import { asText } from "@/lib/format";

export function Metric({ label, value }: { label: string; value: unknown }) {
  const valStr = asText(value);
  // Detect if the value contains numbers, dates, currency symbols, etc.
  const isNumeric = /^[0-9₹%d\s\-:.,\/+]+$/.test(valStr) && valStr !== "—";

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-4.5 shadow-3xs hover:shadow-2xs hover:border-slate-350 transition-all duration-150">
      <div className="text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A]">{label}</div>
      <div className={`mt-2 text-xl font-bold text-[#16202E] ${isNumeric ? "font-mono text-[17px] tracking-tight" : ""}`}>
        {valStr}
      </div>
    </div>
  );
}
