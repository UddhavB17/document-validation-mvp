import { StatusBadge } from "@/components/StatusBadge";
import { ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

import { formatPageRange } from "@/components/applications/review/issueQueue";

export function ReviewerSummary({
  data,
  onSelectPage,
}: {
  data: ApplicationReview;
  onSelectPage?: (pageNo: number) => void;
}) {
  const summary = data.reviewer_summary;
  if (!summary) {
    return null;
  }
  const status = String(summary.overall_status ?? "LIMITED_REVIEW");
  const pagesToReview = Array.isArray(summary.pages_to_review) ? summary.pages_to_review.filter((n): n is number =>
    typeof n === "number" || !isNaN(Number(n))
  ).map(Number) : [];
  const text = asText(summary.note);

  return (
    <div className="space-y-4">
      <section className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-3">
        <h2 className="text-base font-bold text-slate-800">
          Reviewer Action Summary
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={status} />
          <span className="text-sm text-slate-700 font-bold">{asText(summary.message)}</span>
        </div>
        <p className="text-sm text-slate-600 font-medium leading-relaxed">{asText(summary.recommendation)}</p>
        {pagesToReview.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800 shadow-sm">
            <div>
              <div>Pages to check manually: {pagesToReview.length}</div>
              <div className="mt-1 text-xs font-medium text-amber-700" title={formatPageRange(pagesToReview)}>
                Affected pages {formatPageRange(pagesToReview)}
              </div>
            </div>
            {onSelectPage ? (
              <button
                type="button"
                onClick={() => onSelectPage(pagesToReview[0])}
                className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-bold text-amber-800 transition-colors hover:bg-amber-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700"
              >
                Review first page
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
      {text && (
        <section className="space-y-3 rounded-xl border border-slate-200 p-4 shadow-3xs bg-[#F6F7FA]/40">
          <h3 className="text-xs font-bold text-[#5C6B7A] uppercase tracking-widest">Review Summary Notes</h3>
          <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap">{text}</p>
        </section>
      )}
    </div>
  );
}
