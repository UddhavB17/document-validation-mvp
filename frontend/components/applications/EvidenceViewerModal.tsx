import { HighlightedEvidenceText } from "@/components/applications/EvidenceHighlight";
import { EvidenceValue } from "@/components/applications/EvidenceValue";
import { EvidenceSelection } from "@/components/applications/types";
import { api, ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

export function EvidenceViewerModal({
  applicationId,
  data,
  selectedEvidence,
  onClose,
}: {
  applicationId: number;
  data: ApplicationReview;
  selectedEvidence: EvidenceSelection;
  onClose: () => void;
}) {
  const pagesToRender = selectedEvidence.allPageNumbers && selectedEvidence.allPageNumbers.length > 0
    ? selectedEvidence.allPageNumbers
    : [selectedEvidence.pageNumber];

  const firstPage = data.pages.find((item) => Number(item.page_number) === selectedEvidence.pageNumber) ?? null;

  const combinedOcrText = pagesToRender
    .map((pageNo) => {
      const p = data.pages.find((item) => Number(item.page_number) === pageNo);
      return typeof p?.ocr_text === "string" && p.ocr_text.trim()
        ? `--- PAGE ${pageNo} ---\n${p.ocr_text.trim()}`
        : "";
    })
    .filter(Boolean)
    .join("\n\n");

  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-fade-in">
      <div className="bg-white rounded-2xl border border-[#E1E5EB] shadow-2xl w-full max-w-[850px] max-h-[90vh] flex flex-col overflow-hidden">
        <div className="border-b border-[#E1E5EB] bg-[#F6F7FA] px-6 py-4 flex items-center justify-between shrink-0">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-[#5C6B7A]">Evidence viewer</div>
            <div className="font-semibold text-[15px] text-[#16202E] mt-0.5">
              {selectedEvidence.allPageNumbers && selectedEvidence.allPageNumbers.length > 1
                ? `Pages ${selectedEvidence.allPageNumbers.join(", ")} (Combined)`
                : `Page ${selectedEvidence.pageNumber}`}
              {" — "}
              {asText(firstPage?.document_type ?? selectedEvidence.anomaly.document_type)}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {selectedEvidence.allPageNumbers && selectedEvidence.allPageNumbers.length > 1 ? (
              <span className="text-[10px] font-extrabold text-[#2B4C7E] uppercase bg-[#EAF0F8] px-2.5 py-1 rounded border border-[#E1E5EB]">
                Combined Stack
              </span>
            ) : (
              <a
                href={api.sourcePdfUrl(applicationId, selectedEvidence.pageNumber)}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-bold text-[#2B4C7E] hover:underline"
              >
                Open Full PDF
              </a>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-1.5 text-xs font-bold text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E] cursor-pointer"
            >
              Close
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden grid grid-cols-1 md:grid-cols-[1fr_300px] divide-y md:divide-y-0 md:divide-x divide-[#E1E5EB] min-h-0">
          <div className="overflow-y-auto bg-slate-800/10 p-4 flex flex-col gap-4 items-center min-h-0">
            {pagesToRender.map((pageNo) => (
              <div key={pageNo} className="relative w-full flex flex-col items-center max-w-[500px]">
                <div className="absolute top-2 left-2 rounded bg-black/75 px-2 py-0.5 text-[9px] font-mono text-white z-10">
                  Pg {pageNo}
                </div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={api.sourcePageImageUrl(
                    applicationId,
                    pageNo,
                    selectedEvidence.anomaly.found_value || selectedEvidence.anomaly.expected_value || ""
                  )}
                  alt={`Original source PDF page ${pageNo}`}
                  className="h-auto w-full bg-white shadow border border-slate-200 rounded-sm"
                />
              </div>
            ))}
          </div>

          <div className="p-5 overflow-y-auto text-xs space-y-4 shrink-0 bg-white">
            <div className="grid grid-cols-2 gap-3 border-b border-slate-100 pb-4">
              <EvidenceValue label="Expected" value={selectedEvidence.anomaly.expected_value} />
              <EvidenceValue label="Extracted / Found" value={selectedEvidence.anomaly.found_value} />
            </div>
            <div className="space-y-2">
              <div className="font-bold uppercase tracking-wider text-slate-500 text-[10px]">Extracted page text</div>
              <div className="whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono leading-relaxed text-slate-100 text-[11px] max-h-[350px] overflow-y-auto select-all">
                {combinedOcrText ? (
                  <HighlightedEvidenceText text={combinedOcrText.slice(0, 5000)} needle={selectedEvidence.anomaly.found_value ?? ""} />
                ) : (
                  "No OCR text was extracted for this page."
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="border-t border-[#E1E5EB] bg-[#F6F7FA] px-6 py-3.5 flex justify-end shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-5 py-2 text-sm font-semibold text-white shadow-3xs cursor-pointer border-none"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
