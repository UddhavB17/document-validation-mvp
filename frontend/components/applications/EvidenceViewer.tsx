import { api, ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

import { EvidenceSelection } from "./types";

export function EvidenceViewer({
  applicationId,
  data,
  selection,
}: {
  applicationId: number;
  data: ApplicationReview;
  selection: EvidenceSelection | null;
}) {
  if (!selection) {
    return (
      <aside id="evidence-viewer" className="sticky top-4 flex h-[70vh] items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-8 text-center">
        <div>
          <div className="text-base font-bold text-slate-700">Source Evidence Viewer</div>
          <p className="mt-2 max-w-sm text-sm text-slate-500">Select any page number from the checklist, anomalies, or logs to preview the document page here.</p>
        </div>
      </aside>
    );
  }

  const pagesToRender =
    selection.allPageNumbers && selection.allPageNumbers.length > 0 ? selection.allPageNumbers : [selection.pageNumber];

  const firstPage = data.pages.find((item) => Number(item.page_number) === selection.pageNumber);

  const combinedOcrText = pagesToRender
    .map((pageNo) => {
      const page = data.pages.find((item) => Number(item.page_number) === pageNo);
      return typeof page?.ocr_text === "string" && page.ocr_text.trim() ? `--- PAGE ${pageNo} ---\n${page.ocr_text.trim()}` : "";
    })
    .filter(Boolean)
    .join("\n\n");

  return (
    <aside id="evidence-viewer" className="sticky top-4 overflow-hidden rounded-xl border border-slate-300 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-slate-500">Original source evidence</div>
            <div className="font-bold text-slate-900">
              {selection.allPageNumbers && selection.allPageNumbers.length > 1
                ? `Pages ${selection.allPageNumbers.join(", ")} (Combined)`
                : `Page ${selection.pageNumber}`}
              {" · "}
              {asText(firstPage?.document_type ?? selection.anomaly.document_type)}
            </div>
          </div>
          {selection.allPageNumbers && selection.allPageNumbers.length > 1 ? (
            <span className="text-xs font-extrabold text-violet-700 uppercase bg-violet-100 px-2 py-0.5 rounded border border-violet-200 shadow-sm animate-pulse tracking-wide select-none">
              Combined Stack
            </span>
          ) : (
            <a href={api.sourcePdfUrl(applicationId, selection.pageNumber)} target="_blank" rel="noreferrer" className="text-xs font-bold text-blue-700 hover:underline">
              Open full PDF
            </a>
          )}
        </div>
      </div>
      <div
        key={selection.pageNumber + "-" + (selection.allPageNumbers?.join(",") ?? "")}
        className="flex flex-col gap-6 h-[65vh] items-center overflow-auto bg-slate-800 p-4"
      >
        {pagesToRender.map((pageNo) => (
          <div key={pageNo} className="relative w-full flex flex-col items-center">
            <div className="absolute top-2 left-2 rounded bg-black/75 px-2.5 py-1 text-[10px] font-extrabold text-white z-10 shadow border border-slate-700 uppercase tracking-widest select-none">
              Page {pageNo}
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={api.sourcePageImageUrl(applicationId, pageNo)}
              alt={`Original source PDF page ${pageNo}`}
              className="h-auto max-w-full bg-white shadow-lg border border-slate-700 rounded-xs"
            />
          </div>
        ))}
      </div>
      <div className="max-h-[24vh] space-y-3 overflow-auto border-t border-slate-200 p-4 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <EvidenceValue label="Expected" value={selection.anomaly.expected_value} />
          <EvidenceValue label="Extracted / Found" value={selection.anomaly.found_value} />
        </div>
        <div>
          <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">Extracted page text</div>
          <div className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono leading-relaxed text-slate-100">
            {combinedOcrText ? (
              <HighlightedEvidenceText text={combinedOcrText.slice(0, 5000)} needle={selection.anomaly.found_value ?? ""} />
            ) : (
              "No OCR text was extracted for this page. Review the original image above."
            )}
          </div>
        </div>
      </div>
    </aside>
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

function HighlightedEvidenceText({ text, needle }: { text: string; needle: string }) {
  const cleanedNeedle = needle.trim();
  if (cleanedNeedle.length < 4) {
    return <>{text}</>;
  }
  const index = text.toLowerCase().indexOf(cleanedNeedle.toLowerCase());
  if (index < 0) {
    return <>{text}</>;
  }
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-amber-300 px-0.5 text-slate-950">{text.slice(index, index + cleanedNeedle.length)}</mark>
      {text.slice(index + cleanedNeedle.length)}
    </>
  );
}
