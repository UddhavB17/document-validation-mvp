import { asText } from "@/lib/format";

export function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-950">{asText(value)}</div>
    </div>
  );
}
