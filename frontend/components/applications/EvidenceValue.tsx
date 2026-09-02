import { asText } from "@/lib/format";

export function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500 text-[10px]">{label}</div>
      <div className="break-all font-mono text-slate-800 text-[11.5px] whitespace-pre-wrap">{asText(value)}</div>
    </div>
  );
}
