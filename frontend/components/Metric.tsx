import { asText } from "@/lib/format";

export function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 shadow-sm hover:shadow transition-shadow duration-155">
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1.5 text-lg font-bold text-slate-900">{asText(value)}</div>
    </div>
  );
}
