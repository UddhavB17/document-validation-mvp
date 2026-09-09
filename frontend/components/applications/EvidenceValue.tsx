import { asText } from "@/lib/format";

export function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  const text = asText(value);
  return (
    <div>
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500 text-[10px]">{label}</div>
      <div className="max-h-28 overflow-y-auto break-words font-mono text-slate-800 text-[11.5px] whitespace-pre-wrap" title={text.length > 240 ? text : undefined}>
        {text}
      </div>
    </div>
  );
}
