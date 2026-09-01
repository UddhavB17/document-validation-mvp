"use client";

import { useState } from "react";

import { ErrorMessage, InfoMessage } from "@/components/Message";
import { SortableTable } from "@/components/SortableTable";
import { ApplicationReview } from "@/lib/api";
import { decisionNoteSchema } from "@/lib/forms";
import { asText } from "@/lib/format";
import { useCreateDecision, useUndoDecision } from "@/lib/queries";

import { rejectionReasons } from "./types";

export function ManualReviewAndDecision({
  applicationId,
  data,
}: {
  applicationId: number;
  data: ApplicationReview;
}) {
  const [manualConfirmed, setManualConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [showRequestDocs, setShowRequestDocs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createDecision = useCreateDecision(applicationId);
  const undoDecision = useUndoDecision(applicationId);
  const status = String(data.application.status ?? "");
  const latestDecisionId = data.latest_decision?.id;
  const locked = Boolean(data.latest_decision && ["verified", "verified_with_override", "incomplete"].includes(status));

  async function submitDecision(decision: string, reviewerNote: string) {
    setError(null);
    const parsed = decisionNoteSchema.safeParse(reviewerNote);
    if (!parsed.success) {
      setError(parsed.error.errors[0]?.message ?? "Reviewer note is required");
      return;
    }
    await createDecision.mutateAsync({ application_id: applicationId, decision, reviewer_note: parsed.data });
  }

  return (
    <section className="space-y-4">
      <h2 className="text-base font-bold text-slate-800">Manual Review Required</h2>
      <InfoMessage message="Items requiring manual verification cannot be checked automatically." />
      {data.manual_review_items.length > 0 ? (
        <SortableTable
          rows={data.manual_review_items}
          columns={[
            { key: "sno", header: "S.No", value: (row) => asText(row.s_no), sortValue: (row) => String(row.s_no ?? "") },
            { key: "description", header: "Item Description", value: (row) => asText(row.description), sortValue: (row) => String(row.description ?? "") },
            { key: "reason", header: "Why manual review needed", value: (row) => asText(row.reason), sortValue: (row) => String(row.reason ?? "") },
          ]}
        />
      ) : null}

      <label className="flex items-center gap-2.5 text-sm select-none cursor-pointer">
        <input type="checkbox" checked={manualConfirmed} onChange={(event) => setManualConfirmed(event.target.checked)} className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/20" />
        <span className="text-slate-700 font-bold">I confirm I have manually verified all items in the above list</span>
      </label>

      {error ? <ErrorMessage message={error} /> : null}

      {locked ? (
        <div className="space-y-3">
          <InfoMessage message={`Reviewer decision already submitted: ${data.latest_decision?.decision ?? "-"}.`} />
          {latestDecisionId ? (
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50 transition-colors"
              onClick={() => undoDecision.mutate(latestDecisionId)}
            >
              Undo decision
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-3">
          <textarea
            className="h-24 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Reviewer note"
          />
          <div className="flex gap-2">
            <button disabled={!manualConfirmed} className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("ACCEPT", note || "Accepted after manual review.")}>
              Accept
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg bg-blue-600 hover:bg-blue-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("OVERRIDE", note || "Override approved after review.")}>
              Override
            </button>
            <button disabled={!manualConfirmed} className="rounded-lg border border-slate-350 bg-white px-5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:bg-slate-100 disabled:text-slate-400 transition-colors duration-150 shadow-sm" onClick={() => setShowRequestDocs(true)}>
              Request Docs
            </button>
          </div>
          {showRequestDocs ? (
            <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap gap-2">
                {Object.entries(rejectionReasons).map(([label, value]) => (
                  <button key={label} type="button" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors" onClick={() => setNote(value)}>
                    {label}
                  </button>
                ))}
              </div>
              <button disabled={!manualConfirmed} className="rounded-lg bg-red-600 hover:bg-red-500 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300 disabled:text-slate-500 transition-colors duration-150 shadow-sm" onClick={() => submitDecision("REQUEST_DOCS", note)}>
                Submit request for documents
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
