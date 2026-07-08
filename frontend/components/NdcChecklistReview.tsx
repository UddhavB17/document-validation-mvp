import type React from "react";
import type { ChecklistItem, ChecklistVerificationResponse } from "../generated/checklistTypes";

type Props = {
  data: ChecklistVerificationResponse;
};

const statusStyles = {
  verified: "border-emerald-700/40 bg-emerald-950/30 text-emerald-200",
  needs_review: "border-amber-600/50 bg-amber-950/30 text-amber-100",
  missing: "border-rose-700/50 bg-rose-950/30 text-rose-100",
  unknown: "border-slate-600/60 bg-slate-900 text-slate-100",
};

const statusIcons = {
  verified: "OK",
  needs_review: "!",
  missing: "X",
  unknown: "?",
};

export function NdcChecklistReview({ data }: Props) {
  return (
    <section className="min-h-screen bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-semibold">NDC checklist review</h1>
            <p className="text-sm text-slate-400">Loan file {data.loan_file_id}</p>
          </div>
          <SummaryBar data={data} />
        </header>

        <div className="overflow-hidden rounded-md border border-slate-800">
          {data.items.map((item) => (
            <ChecklistRow key={item.item_number} item={item} />
          ))}
        </div>
      </div>
    </section>
  );
}

function SummaryBar({ data }: Props) {
  const items = [
    ["Verified", data.summary.verified, "text-emerald-300"],
    ["Need review", data.summary.needs_review, "text-amber-300"],
    ["Missing", data.summary.missing, "text-rose-300"],
    ["Unknown", data.summary.unknown, "text-slate-300"],
  ] as const;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map(([label, value, color]) => (
        <div key={label} className="rounded-md border border-slate-800 bg-slate-900 px-4 py-3">
          <div className={`text-xl font-semibold ${color}`}>{value}/{data.summary.total}</div>
          <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
        </div>
      ))}
    </div>
  );
}

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const expanded = item.status !== "verified";

  return (
    <details open={expanded} className="group border-b border-slate-800 last:border-b-0">
      <summary className="grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 bg-slate-950 px-4 py-3 hover:bg-slate-900">
        <span className={`flex h-7 w-7 items-center justify-center rounded-full border text-sm ${statusStyles[item.status]}`}>
          {statusIcons[item.status]}
        </span>
        <div className="min-w-0">
          <div className="truncate font-medium">
            {item.item_number}. {item.document_name}
          </div>
          <div className="text-sm text-slate-500">{item.confidence_detail}</div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Badge>{item.status.replace("_", " ")}</Badge>
          <Badge>{item.confidence}</Badge>
          {item.extraction_source === "llm_fallback" && (
            <Badge tone="warning">Sent to LLM fallback - recommend manual check</Badge>
          )}
        </div>
      </summary>

      <div className="grid gap-4 bg-slate-900/70 px-4 py-4 md:grid-cols-[1fr_1.2fr]">
        <div className="space-y-3">
          {item.narration && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Narration</div>
              <p className="mt-1 text-sm text-slate-200">{item.narration}</p>
            </div>
          )}
          {item.flagged_reason && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Flagged reason</div>
              <p className="mt-1 font-mono text-sm text-slate-200">{item.flagged_reason}</p>
            </div>
          )}
        </div>

        <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Extracted fields</div>
          {Object.keys(item.extracted_fields).length === 0 ? (
            <p className="text-sm text-slate-500">No fields extracted.</p>
          ) : (
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Object.entries(item.extracted_fields).map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="truncate text-xs text-slate-500">{key}</dt>
                  <dd className="break-words text-sm text-slate-100">{value ?? "-"}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </details>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "warning" }) {
  const className =
    tone === "warning"
      ? "border-amber-500/50 bg-amber-950/50 text-amber-200"
      : "border-slate-700 bg-slate-900 text-slate-300";
  return (
    <span className={`rounded-md border px-2 py-1 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}
