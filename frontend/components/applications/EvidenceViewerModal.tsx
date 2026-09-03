"use client";

import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import { AiExplanationDisclosure } from "@/components/applications/AiAuditInsights";
import { HighlightedEvidenceText } from "@/components/applications/EvidenceHighlight";
import { EvidenceValue } from "@/components/applications/EvidenceValue";
import { getAffectedPages, getReviewIssueKey } from "@/components/applications/review/issueQueue";
import {
  getReviewIssueState,
  markReviewIssueChecked,
  markReviewIssueViewed,
} from "@/components/applications/review/sessionState";
import { EvidenceSelection } from "@/components/applications/types";
import { api, ApplicationReview } from "@/lib/api";
import { asText } from "@/lib/format";

const MAX_OCR_PREVIEW = 5000;

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  ));
}

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
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const ocrSectionRef = useRef<HTMLDivElement>(null);
  const pages = useMemo(() => {
    const selectedPages = selectedEvidence.allPageNumbers?.length
      ? selectedEvidence.allPageNumbers
      : [selectedEvidence.pageNumber];
    return [...new Set(selectedPages.filter((page) => Number.isFinite(page) && page > 0))].sort((a, b) => a - b);
  }, [selectedEvidence]);
  const [activePage, setActivePage] = useState(selectedEvidence.pageNumber);
  const [jumpValue, setJumpValue] = useState("1");
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [imageReady, setImageReady] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [showFullOcr, setShowFullOcr] = useState(false);
  const issueKey = getReviewIssueKey(applicationId, selectedEvidence.anomaly);
  const [isChecked, setIsChecked] = useState(() => getReviewIssueState(issueKey) === "Checked");

  useEffect(() => {
    const nextPage = pages.includes(selectedEvidence.pageNumber) ? selectedEvidence.pageNumber : pages[0];
    setActivePage(nextPage ?? selectedEvidence.pageNumber);
    setJumpValue(String(Math.max(1, pages.indexOf(nextPage ?? selectedEvidence.pageNumber) + 1)));
    setZoom(1);
    setRotation(0);
    setImageReady(false);
    setImageError(false);
    setShowFullOcr(false);
    setIsChecked(getReviewIssueState(issueKey) === "Checked");
  }, [issueKey, pages, selectedEvidence]);

  const activeIndex = Math.max(0, pages.indexOf(activePage));
  const renderedPage = pages[activeIndex] ?? activePage;
  const activePageData = data.pages.find((page) => Number(page.page_number) === renderedPage);
  const ocrText = typeof activePageData?.ocr_text === "string" ? activePageData.ocr_text.trim() : "";
  const ocrIsTruncated = ocrText.length > MAX_OCR_PREVIEW;
  const visibleOcrText = showFullOcr ? ocrText : ocrText.slice(0, MAX_OCR_PREVIEW);
  const adjacentPage = pages.length > 1 ? pages[activeIndex + 1] ?? pages[activeIndex - 1] : undefined;
  const imageHighlight = String(selectedEvidence.anomaly.found_value || selectedEvidence.anomaly.expected_value || "").slice(0, 160);
  const adjacentImageUrl = adjacentPage
    ? api.sourcePageImageUrl(applicationId, adjacentPage, imageHighlight)
    : null;
  const evidenceReady = imageReady || imageError;

  useEffect(() => {
    markReviewIssueViewed(issueKey);
  }, [issueKey]);

  useEffect(() => {
    setImageReady(false);
    setImageError(false);
    setZoom(1);
    setRotation(0);
    setShowFullOcr(false);
  }, [renderedPage]);

  useEffect(() => {
    const previousActiveElement = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    closeButtonRef.current?.focus();
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const elements = focusableElements(dialog);
      if (elements.length === 0) {
        event.preventDefault();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
      previousActiveElement?.focus();
    };
  }, [onClose]);

  const moveToAffectedPage = (nextIndex: number) => {
    if (nextIndex < 0 || nextIndex >= pages.length) return;
    setActivePage(pages[nextIndex]);
    setJumpValue(String(nextIndex + 1));
  };

  const submitPageJump = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextIndex = Number.parseInt(jumpValue, 10) - 1;
    if (Number.isInteger(nextIndex) && nextIndex >= 0 && nextIndex < pages.length) {
      moveToAffectedPage(nextIndex);
    } else {
      setJumpValue(String(activeIndex + 1));
    }
  };

  const markChecked = () => {
    markReviewIssueChecked(issueKey);
    setIsChecked(true);
  };

  return (
    <div
      id="evidence-viewer"
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-slate-950/70 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {adjacentImageUrl ? <link rel="prefetch" as="image" href={adjacentImageUrl} /> : null}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-workspace-heading"
        aria-describedby="evidence-workspace-description"
        tabIndex={-1}
        className="flex h-full max-h-full w-full flex-col overflow-hidden rounded-none border border-slate-200 bg-white shadow-2xl sm:h-[92vh] sm:max-h-[900px] sm:max-w-[1100px] sm:rounded-2xl"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 bg-[#F6F7FA] px-4 py-3 sm:px-6 sm:py-4">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[#5C6B7A]">Evidence workspace</p>
            <h1 id="evidence-workspace-heading" className="mt-1 truncate text-sm font-bold text-[#16202E] sm:text-base">
              Affected page {activeIndex + 1} of {Math.max(1, pages.length)} · PDF page {renderedPage}
            </h1>
            <p id="evidence-workspace-description" className="mt-1 max-w-3xl truncate text-xs font-medium text-slate-600">
              {asText(selectedEvidence.anomaly.reason ?? selectedEvidence.anomaly.rule_id)}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close evidence workspace"
            className="shrink-0 rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-bold text-[#5C6B7A] transition-colors hover:bg-slate-50 hover:text-[#16202E] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
          >
            Close
          </button>
        </header>

        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <nav aria-label="Affected page navigation" className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => moveToAffectedPage(activeIndex - 1)}
              disabled={activeIndex === 0}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
            >
              Previous affected page
            </button>
            <form onSubmit={submitPageJump} className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
              <label htmlFor="affected-page-position" className="sr-only">Affected page position</label>
              <input
                id="affected-page-position"
                type="number"
                inputMode="numeric"
                min={1}
                max={Math.max(1, pages.length)}
                value={jumpValue}
                onChange={(event) => setJumpValue(event.target.value)}
                aria-label="Affected page position"
                className="w-14 rounded-md border border-slate-300 px-2 py-1.5 text-center font-mono text-xs font-bold text-slate-900 focus:border-[#2B4C7E] focus:outline-none focus:ring-2 focus:ring-[#2B4C7E]/20"
              />
              <span>of {Math.max(1, pages.length)}</span>
              <button type="submit" className="rounded-md border border-slate-300 bg-slate-50 px-2 py-1.5 text-[10px] font-bold text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]">
                Jump
              </button>
            </form>
            <button
              type="button"
              onClick={() => moveToAffectedPage(activeIndex + 1)}
              disabled={activeIndex >= pages.length - 1}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
            >
              Next affected page
            </button>
          </nav>
          <div aria-live="polite" className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Showing PDF page {renderedPage} · active page only
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden md:grid md:grid-cols-[minmax(0,1fr)_360px]">
          <section aria-labelledby="source-image-heading" className="flex min-h-[32vh] min-w-0 flex-col overflow-hidden border-b border-slate-200 bg-slate-800/10 md:min-h-0 md:border-b-0 md:border-r">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white/90 px-4 py-2.5">
              <h2 id="source-image-heading" className="text-xs font-bold uppercase tracking-wider text-slate-600">Source image</h2>
              <div role="toolbar" aria-label="Image controls" className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setZoom((value) => Math.max(0.75, Number((value - 0.25).toFixed(2))))}
                  disabled={zoom <= 0.75 || imageError}
                  aria-label="Zoom out"
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                >
                  −
                </button>
                <span className="min-w-12 text-center font-mono text-[10px] font-bold text-slate-600">{Math.round(zoom * 100)}%</span>
                <button
                  type="button"
                  onClick={() => setZoom((value) => Math.min(1.75, Number((value + 0.25).toFixed(2))))}
                  disabled={zoom >= 1.75 || imageError}
                  aria-label="Zoom in"
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-sm font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                >
                  +
                </button>
                <button
                  type="button"
                  onClick={() => setRotation((value) => (value + 90) % 360)}
                  disabled={imageError}
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                >
                  Rotate 90°
                </button>
                <button
                  type="button"
                  onClick={() => ocrSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                >
                  Jump to OCR
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-4">
              {imageError ? (
                <div role="alert" className="mx-auto flex max-w-md flex-col items-center justify-center rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
                  <h3 className="text-sm font-bold text-amber-900">Page image could not be rendered</h3>
                  <p className="mt-2 text-xs font-medium leading-relaxed text-amber-800">Use the original PDF for this page. The review workspace remains available for the rule details and OCR returned by the review API.</p>
                  <a
                    href={api.sourcePdfUrl(applicationId, renderedPage)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-4 rounded-lg bg-[#2B4C7E] px-4 py-2 text-xs font-bold text-white hover:bg-[#1E3559] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                  >
                    Open full PDF at page {renderedPage}
                  </a>
                </div>
              ) : (
                <div className="flex min-h-full min-w-full items-start justify-center">
                  <div className="relative flex min-h-48 min-w-48 items-center justify-center" style={{ transform: `scale(${zoom}) rotate(${rotation}deg)`, transformOrigin: "top center" }}>
                    {!imageReady ? <span role="status" className="absolute z-10 rounded bg-slate-900/80 px-3 py-2 text-xs font-semibold text-white">Loading page image…</span> : null}
                    <Image
                      key={renderedPage}
                      src={api.sourcePageImageUrl(
                        applicationId,
                        renderedPage,
                        imageHighlight,
                      )}
                      alt={`Original source PDF page ${renderedPage}`}
                      width={720}
                      height={1020}
                      unoptimized
                      onLoad={() => setImageReady(true)}
                      onError={() => {
                        setImageReady(false);
                        setImageError(true);
                      }}
                      className="h-auto max-w-full rounded-sm border border-slate-200 bg-white shadow"
                    />
                  </div>
                </div>
              )}
            </div>
          </section>

          <aside className="min-h-0 overflow-y-auto bg-white p-4 sm:p-5">
            <section aria-labelledby="rule-detail-heading" className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <h2 id="rule-detail-heading" className="text-sm font-bold text-slate-900">Deterministic rule detail</h2>
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Primary basis</span>
              </div>
              <div className="grid grid-cols-2 gap-3 border-b border-slate-100 pb-4">
                <EvidenceValue label="Rule ID" value={selectedEvidence.anomaly.rule_id} />
                <EvidenceValue label="Severity" value={selectedEvidence.anomaly.severity} />
                <EvidenceValue label="Document type" value={activePageData?.document_type ?? selectedEvidence.anomaly.document_type ?? "File-level"} />
                <EvidenceValue label="PDF page" value={renderedPage} />
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Why this is flagged</div>
                <p className="text-xs font-semibold leading-relaxed text-slate-800">{asText(selectedEvidence.anomaly.reason ?? selectedEvidence.anomaly.rule_id)}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 border-b border-slate-100 pb-4">
                <EvidenceValue label="Expected" value={selectedEvidence.anomaly.expected_value} />
                <EvidenceValue label="Found" value={selectedEvidence.anomaly.found_value} />
              </div>
            </section>

            <div ref={ocrSectionRef} id="evidence-ocr" className="mt-5 space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">Active-page OCR</h2>
                <span className="text-[10px] font-semibold text-slate-400">PDF page {renderedPage} only</span>
              </div>
              <div className="max-h-80 overflow-y-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
                {visibleOcrText ? (
                  <HighlightedEvidenceText
                    text={visibleOcrText}
                    needle={selectedEvidence.anomaly.found_value ?? selectedEvidence.anomaly.expected_value ?? ""}
                  />
                ) : "No OCR text was extracted for this page."}
              </div>
              {ocrIsTruncated ? (
                <button
                  type="button"
                  onClick={() => setShowFullOcr((value) => !value)}
                  className="text-xs font-bold text-[#2B4C7E] underline decoration-dotted underline-offset-2 hover:text-[#1E3559] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
                >
                  {showFullOcr ? "Show preview" : "Show full text"}
                </button>
              ) : null}
            </div>

            <div className="mt-5">
              <AiExplanationDisclosure data={data} anomaly={selectedEvidence.anomaly} pageNumber={renderedPage} />
            </div>
          </aside>
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-slate-200 bg-[#F6F7FA] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="text-[10px] font-semibold leading-relaxed text-slate-500">
            Evidence status is this-session state only; it is not written back as a persistent acknowledgment.
            {!evidenceReady ? <span className="ml-1 text-amber-700">Waiting for evidence to load.</span> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={api.sourcePdfUrl(applicationId, renderedPage)}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
            >
              Open full PDF
            </a>
            <button
              type="button"
              onClick={markChecked}
              disabled={!evidenceReady || isChecked}
              className="rounded-lg bg-[#2B4C7E] px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-[#1E3559] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2B4C7E]"
            >
              {isChecked ? "Checked in this session" : "Mark checked"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
