import { InfoMessage } from "@/components/Message";
import { Anomaly, ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

import { AiAuditInsights } from "./AiAuditInsights";
import { getSeverityBadgeColor } from "./types";

export function Anomalies({
  data,
  onSelectEvidence,
}: {
  data: ApplicationReview;
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => void;
}) {
  const business = data.summary.business_anomalies;
  const processing = data.summary.processing_warnings;
  if (business.length === 0 && processing.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-bold text-slate-800">Exceptions and Quality Warnings</h2>
        <InfoMessage message="No issues detected." />
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <AiAuditInsights data={data} onSelectEvidence={onSelectEvidence} />
      <AnomalyGroup
        title={`Business Checklist Exceptions (${business.length})`}
        description="Document, identity, field, date, and policy exceptions that can affect the operational decision."
        anomalies={business}
        tone="business"
        onSelectEvidence={onSelectEvidence}
      />
      <AnomalyGroup
        title={`Processing Quality Warnings (${processing.length})`}
        description="OCR, classification, ownership, and page-processing limitations. These require evidence review but are not business failures by themselves."
        anomalies={processing}
        tone="processing"
        onSelectEvidence={onSelectEvidence}
      />
    </section>
  );
}

function AnomalyGroup({
  title,
  description,
  anomalies,
  tone,
  onSelectEvidence,
}: {
  title: string;
  description: string;
  anomalies: Anomaly[];
  tone: "business" | "processing";
  onSelectEvidence: (anomaly: Anomaly, pageNumber: number, allPageNumbers?: number[]) => void;
}) {
  return (
    <section className="space-y-3">
      <div className={`rounded-xl border px-4 py-3 ${tone === "business" ? "border-red-200 bg-red-50" : "border-blue-200 bg-blue-50"}`}>
        <h2 className="text-base font-bold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs font-medium text-slate-600">{description}</p>
      </div>
      {anomalies.length === 0 ? <InfoMessage message={`No ${tone === "business" ? "business exceptions" : "processing warnings"}.`} /> : null}
      <div className="space-y-2">
        {anomalies.map((anomaly, index) => {
          const isHigh = anomaly.severity === "HIGH";
          const pages = anomaly.collapsed_page_numbers?.length
            ? anomaly.collapsed_page_numbers
            : typeof anomaly.page_number === "number"
              ? [anomaly.page_number]
              : [];
          const severityColors = isHigh
            ? "border-red-200 bg-red-50 text-red-800"
            : anomaly.severity === "MEDIUM"
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : "border-slate-200 bg-slate-50 text-slate-800";
          return (
            <details key={`${anomaly.rule_id}-${anomaly.id ?? index}`} className={`overflow-hidden rounded-xl border shadow-sm ${severityColors}`} open={index === 0 && isHigh}>
              <summary className="flex cursor-pointer items-center justify-between px-4 py-3 font-semibold hover:bg-white/50">
                <div className="flex items-center gap-3">
                  <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-bold uppercase ${getSeverityBadgeColor(anomaly.severity)}`}>
                    {anomaly.severity}
                  </span>
                  {anomaly.document_type ? (
                    <span className="inline-flex rounded bg-white/70 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-700">
                      {anomaly.document_type}
                    </span>
                  ) : null}
                  <span className="text-sm">{anomaly.reason ?? anomaly.rule_id}</span>
                </div>
              </summary>
              <div className="space-y-4 border-t border-slate-200 bg-white px-4 py-3 text-xs">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
                  <EvidenceValue label="Expected" value={anomaly.expected_value} />
                  <EvidenceValue label="Found" value={anomaly.found_value} />
                  <EvidenceValue label="Document Type" value={anomaly.document_type ?? "File-level"} />
                  <EvidenceValue label="Severity" value={anomaly.severity} />
                  <EvidenceValue label="Rule ID" value={anomaly.rule_id} />
                </div>
                {pages.length ? (
                  <div>
                    <div className="mb-2 font-semibold uppercase tracking-wider text-slate-500">Open source evidence</div>
                    <div className="flex flex-wrap gap-2 items-center">
                      {pages.length > 1 ? (
                        <button
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pages[0], pages)}
                          className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 font-bold text-violet-700 hover:bg-violet-100 transition-colors shadow-sm"
                        >
                          👁️ View Combined ({pages.length} pgs)
                        </button>
                      ) : null}
                      {pages.slice(0, 12).map((pageNumber) => (
                        <button
                          key={pageNumber}
                          type="button"
                          onClick={() => onSelectEvidence(anomaly, pageNumber)}
                          className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 font-bold text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          Page {pageNumber}
                        </button>
                      ))}
                      {pages.length > 12 ? <span className="px-2 py-1.5 font-semibold text-slate-500">+{pages.length - 12} more pages</span> : null}
                    </div>
                  </div>
                ) : (
                  <p className="font-medium text-slate-500">This is a file-level exception with no single source page.</p>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="break-all font-mono text-slate-800">{asText(value)}</div>
    </div>
  );
}
