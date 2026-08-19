import React, { useState, useEffect, useRef } from "react";
import type { ChecklistItem, ChecklistVerificationResponse, ChecklistStatus } from "../generated/checklistTypes";

type Props = {
  data: ChecklistVerificationResponse;
  onSubmitReview?: (payload: {
    overrides: Record<number, boolean>;
    confirmedMissing: Record<number, boolean>;
    notes: Record<number, string>;
  }) => void;
  isSubmitting?: boolean;
};

const statusStyles: Record<string, string> = {
  required_and_present: "border-emerald-700/40 bg-emerald-950/30 text-emerald-200",
  required_and_missing: "border-rose-700/50 bg-rose-950/30 text-rose-100",
  not_applicable: "border-sky-700/40 bg-sky-950/30 text-sky-100",
  not_evaluated_by_engine: "border-amber-600/50 bg-amber-950/30 text-amber-100",
};

const statusIcons: Record<string, string> = {
  required_and_present: "OK",
  required_and_missing: "X",
  not_applicable: "N/A",
  not_evaluated_by_engine: "!",
};

export function isExceptionStatus(status: ChecklistStatus): boolean {
  switch (status) {
    case "required_and_missing":
    case "missing":
    case "not_evaluated_by_engine":
    case "needs_review":
    case "unknown":
      return true;
    case "required_and_present":
    case "verified":
    case "not_applicable":
      return false;
    default:
      // Treat unrecognized statuses as exceptions by default for safety
      return true;
  }
}

export function NdcChecklistReview({ data, onSubmitReview, isSubmitting = false }: Props) {
  // Normalize legacy status values from backend dynamically if they exist
  const items = data.items.map(item => {
    let status = item.status as string;
    if (status === "verified") status = "required_and_present";
    if (status === "missing") status = "required_and_missing";
    if (status === "needs_review" || status === "unknown") status = "not_evaluated_by_engine";
    return { ...item, status: status as ChecklistStatus };
  });

  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  const [confirmedMissing, setConfirmedMissing] = useState<Record<number, boolean>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [isVerifiedExpanded, setIsVerifiedExpanded] = useState<boolean>(false);
  const [activeExceptionIndex, setActiveExceptionIndex] = useState<number>(0);
  
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({});

  // Filter items explicitly using the classification helper
  const exceptions = items.filter(item => isExceptionStatus(item.status));
  const verifiedOk = items.filter(item => !isExceptionStatus(item.status));

  // Status Counts
  const countPresent = items.filter(i => i.status === "required_and_present").length;
  const countMissing = items.filter(i => i.status === "required_and_missing").length;
  const countNA = items.filter(i => i.status === "not_applicable").length;
  const countNotEvaluated = items.filter(i => i.status === "not_evaluated_by_engine").length;

  let trafficLight: "red" | "amber" | "green" = "green";
  if (countMissing > 0) {
    trafficLight = "red";
  } else if (countNotEvaluated > 0) {
    trafficLight = "amber";
  }

  // Keyboard Navigation: Initial Focus
  useEffect(() => {
    if (exceptions.length > 0) {
      setActiveExceptionIndex(0);
      const firstActiveItem = exceptions[0].item_number;
      setTimeout(() => {
        cardRefs.current[firstActiveItem]?.focus();
      }, 50);
    } else {
      setTimeout(() => {
        document.getElementById("clean-success-block")?.focus();
      }, 50);
    }
  }, [exceptions.length]);

  // Focus active exception card on index change
  useEffect(() => {
    if (exceptions.length > 0 && activeExceptionIndex >= 0 && activeExceptionIndex < exceptions.length) {
      const activeItemNumber = exceptions[activeExceptionIndex].item_number;
      cardRefs.current[activeItemNumber]?.focus();
    }
  }, [activeExceptionIndex, exceptions]);

  // Focus transition logic helper
  const transitionFocus = () => {
    if (activeExceptionIndex === exceptions.length - 1) {
      setTimeout(() => {
        document.getElementById("verified-ok-toggle")?.focus();
      }, 50);
    } else {
      setActiveExceptionIndex(prev => prev + 1);
    }
  };

  const handleApprove = (item: ChecklistItem) => {
    setOverrides(prev => ({ ...prev, [item.item_number]: !prev[item.item_number] }));
    transitionFocus();
  };

  const handleConfirmMissing = (item: ChecklistItem) => {
    setConfirmedMissing(prev => ({ ...prev, [item.item_number]: !prev[item.item_number] }));
    transitionFocus();
  };

  const handleOpenNote = (item: ChecklistItem) => {
    document.getElementById(`note-${item.item_number}`)?.focus();
  };

  const handleApproveAll = () => {
    if (onSubmitReview) {
      onSubmitReview({
        overrides: {},
        confirmedMissing: {},
        notes: {}
      });
    }
  };

  const handleSubmit = () => {
    if (onSubmitReview) {
      onSubmitReview({ overrides, confirmedMissing, notes });
    }
  };

  // Warn on unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const hasChanges = Object.keys(overrides).length > 0 || 
                         Object.keys(confirmedMissing).length > 0 || 
                         Object.keys(notes).length > 0;
      if (hasChanges) {
        e.preventDefault();
        e.returnValue = "You have unsaved review decisions. Are you sure you want to leave?";
        return e.returnValue;
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [overrides, confirmedMissing, notes]);

  // PERSISTENCE MODEL: All overrides, confirmations of missing documents, and note edits
  // are saved locally in component state (`overrides`, `confirmedMissing`, `notes`) and
  // are batched together until they are persisted in a single mutation upon final Submit
  // (or Shift+Enter). This avoids redundant database calls and half-completed review saves.
  // Keyboard Shortcuts listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore shortcuts when editing note inputs
      if (document.activeElement?.tagName === "INPUT" || document.activeElement?.tagName === "TEXTAREA") {
        return;
      }

      // Shift+Enter to submit
      if (e.shiftKey && e.key === "Enter") {
        e.preventDefault();
        if (exceptions.length === 0) {
          handleApproveAll();
        } else {
          handleSubmit();
        }
        return;
      }

      if (exceptions.length === 0) return;
      const activeItem = exceptions[activeExceptionIndex];

      switch (e.key) {
        case "ArrowRight":
          e.preventDefault();
          setActiveExceptionIndex(prev => (prev + 1) % exceptions.length);
          break;
        case "ArrowLeft":
          e.preventDefault();
          setActiveExceptionIndex(prev => (prev - 1 + exceptions.length) % exceptions.length);
          break;
        case "a":
        case "A":
          e.preventDefault();
          handleApprove(activeItem);
          break;
        case "m":
        case "M":
          e.preventDefault();
          handleConfirmMissing(activeItem);
          break;
        case "n":
        case "N":
          e.preventDefault();
          handleOpenNote(activeItem);
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [exceptions, activeExceptionIndex, overrides, confirmedMissing, notes]);

  return (
    <section className="min-h-screen bg-slate-950 p-6 text-slate-100 font-sans">
      <div className="mx-auto max-w-7xl space-y-6">
        
        {/* Title area & Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
              <span>NDC Checklist Review</span>
              <span className={`relative flex h-3.5 w-3.5`}>
                {trafficLight === "red" && (
                  <>
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-rose-500 shadow-[0_0_10px_#f43f5e]"></span>
                  </>
                )}
                {trafficLight === "amber" && (
                  <>
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-amber-500 shadow-[0_0_10px_#f59e0b]"></span>
                  </>
                )}
                {trafficLight === "green" && (
                  <>
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-emerald-500 shadow-[0_0_10px_#10b981]"></span>
                  </>
                )}
              </span>
            </h1>
            <p className="text-sm text-slate-400 font-medium">Loan file ID: <span className="font-mono text-slate-200">{data.loan_file_id}</span></p>
          </div>
          
          {/* Summary status counts */}
          <div className="flex flex-wrap gap-3">
            <SummaryBlock label="Present" count={countPresent} total={items.length} color="text-emerald-400" border="border-emerald-500/20" />
            <SummaryBlock label="Missing" count={countMissing} total={items.length} color="text-rose-400" border="border-rose-500/20" />
            <SummaryBlock label="Not Evaluated" count={countNotEvaluated} total={items.length} color="text-amber-400" border="border-amber-500/20" />
            <SummaryBlock label="N/A" count={countNA} total={items.length} color="text-sky-400" border="border-sky-500/20" />
          </div>
        </header>

        {/* Exceptions section */}
        <section className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-900 pb-2">
            <h2 className="text-base font-bold text-slate-200 flex items-center gap-2">
              <span>Exceptions &amp; Warnings</span>
              <span className="rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 px-2 py-0.5 text-[11px] font-extrabold font-mono">
                {exceptions.length}
              </span>
            </h2>
          </div>

          {exceptions.length === 0 ? (
            /* Zero-Exception Clean State */
            <div
              id="clean-success-block"
              tabIndex={0}
              className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-8 text-center space-y-4 shadow-sm outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <div className="mx-auto h-12 w-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xl font-bold">
                ✓
              </div>
              <div className="space-y-1">
                <h3 className="text-lg font-bold text-slate-200">No exceptions — ready to approve</h3>
                <p className="text-sm text-slate-400">All required documents are present and successfully verified.</p>
              </div>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleApproveAll}
                  className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-5 py-2 text-sm font-semibold text-white shadow-sm transition-all active:scale-[0.98] cursor-pointer border-none"
                >
                  Approve Application (Shift+Enter)
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {exceptions.map((item, index) => {
                const isActive = index === activeExceptionIndex;
                const isOverridden = overrides[item.item_number] || false;
                const isConfMissing = confirmedMissing[item.item_number] || false;
                const noteVal = notes[item.item_number] || "";

                // Parse page number if present in confidence details
                const pageMatch = item.confidence_detail.match(/page\s*(\d+)/i) || item.confidence_detail.match(/pg\s*(\d+)/i) || item.confidence_detail.match(/page\(s\)\s*(\d+)/i);
                const pageNo = pageMatch ? Number(pageMatch[1]) : null;

                return (
                  <div
                    key={item.item_number}
                    ref={el => { cardRefs.current[item.item_number] = el; }}
                    tabIndex={0}
                    className={`rounded-xl border p-5 transition-all duration-200 outline-none select-none ${
                      isActive
                        ? "border-violet-500 bg-slate-900 shadow-[0_0_15px_rgba(139,92,246,0.12)] ring-1 ring-violet-500"
                        : "border-slate-800 bg-slate-900/40 hover:border-slate-700"
                    }`}
                  >
                    {/* Item row header */}
                    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 pb-3 mb-4">
                      <div className="min-w-0">
                        <h3 className="truncate font-semibold text-slate-100 flex items-center gap-2">
                          <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-extrabold ${statusStyles[item.status]}`}>
                            {statusIcons[item.status]}
                          </span>
                          <span>{item.item_number}. {item.document_name}</span>
                        </h3>
                        <p className="text-xs text-slate-400 mt-1 font-medium">{item.confidence_detail}</p>
                      </div>
                      
                      <div className="flex flex-wrap gap-1.5">
                        {isOverridden && (
                          <span className="rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 text-[10px] font-bold uppercase">
                            Overridden/Approved
                          </span>
                        )}
                        {isConfMissing && (
                          <span className="rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 px-2 py-0.5 text-[10px] font-bold uppercase">
                            Confirmed Missing
                          </span>
                        )}
                        <span className="rounded bg-slate-800 border border-slate-700 px-2.5 py-0.5 text-[10px] font-semibold text-slate-355">
                          {item.status.replace(/_/g, " ")}
                        </span>
                        <span className="rounded bg-slate-800 border border-slate-700 px-2.5 py-0.5 text-[10px] font-semibold text-slate-355">
                          {item.confidence}
                        </span>
                      </div>
                    </div>

                    {/* Side-by-side Panel */}
                    <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
                      
                      {/* Left: Extracted fields / Narration / Warnings */}
                      <div className="space-y-4">
                        {item.narration && (
                          <div className="rounded-lg bg-slate-950 p-3 border border-slate-850">
                            <span className="text-[9px] font-extrabold uppercase tracking-wider text-slate-500 block">Narration Explanation</span>
                            <p className="mt-1 text-xs text-slate-300 leading-relaxed font-medium">{item.narration}</p>
                          </div>
                        )}
                        
                        {item.flagged_reason && (
                          <div className="rounded-lg bg-rose-950/20 border border-rose-900/30 p-3 flex gap-2">
                            <span className="text-rose-400 text-xs">⚠️</span>
                            <div>
                              <span className="text-[9px] font-extrabold uppercase tracking-wider text-rose-400 block">Rule Flagged Reason</span>
                              <p className="mt-0.5 font-mono text-[11px] text-rose-300 leading-relaxed font-semibold">{item.flagged_reason}</p>
                            </div>
                          </div>
                        )}

                        <div className="rounded-lg bg-slate-950/60 border border-slate-850 p-3">
                          <span className="text-[9px] font-extrabold uppercase tracking-wider text-slate-500 block mb-2">Extracted Data Parameters</span>
                          {Object.keys(item.extracted_fields).length === 0 ? (
                            <p className="text-xs text-slate-500 italic">No parameters extracted.</p>
                          ) : (
                            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                              {Object.entries(item.extracted_fields).map(([key, value]) => (
                                <div key={key} className="min-w-0">
                                  <dt className="truncate text-[10px] font-bold text-slate-500 uppercase tracking-wider">{key.replace(/_/g, " ")}</dt>
                                  <dd className="break-words text-xs text-slate-200 font-mono mt-0.5 font-semibold">{value ?? "—"}</dd>
                                </div>
                              ))}
                            </dl>
                          )}
                        </div>
                      </div>

                      {/* Right: Document page thumbnail / crop mockup */}
                      <div className="flex flex-col">
                        <div className="relative overflow-hidden rounded-lg border border-slate-800 bg-slate-950 w-full h-full min-h-[160px] flex flex-col justify-between p-3.5 shadow-inner">
                          <div className="flex items-start justify-between">
                            <span className="rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-[9px] font-bold text-slate-400 uppercase tracking-wider">
                              {item.extraction_source.replace("_", " ")}
                            </span>
                            <span className="text-[9px] font-mono text-slate-500">
                              PAGE CROP PREVIEW
                            </span>
                          </div>
                          
                          <div className="my-2 flex flex-col items-center justify-center text-center">
                            <svg className="h-8 w-8 text-violet-500/80 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                            </svg>
                            <span className="text-[11px] font-bold text-slate-355">{item.document_name}</span>
                            {pageNo ? (
                              <span className="text-[9.5px] font-mono text-violet-400 font-bold mt-0.5">Page {pageNo} Source</span>
                            ) : (
                              <span className="text-[10px] text-slate-500 italic mt-0.5">Mock Document Image</span>
                            )}
                          </div>
                          
                          <div className="text-[8.5px] text-slate-500 truncate w-full text-center">
                            {item.confidence_detail}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Bottom actions panel */}
                    <div className="flex flex-wrap items-center justify-between gap-3 mt-4 pt-3 border-t border-slate-800/80">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleApprove(item)}
                          className={`rounded-lg border px-3.5 py-1.5 text-xs font-bold transition-all duration-150 cursor-pointer ${
                            isOverridden
                              ? "bg-emerald-600 border-emerald-500 text-white shadow-sm"
                              : "bg-slate-900 border-slate-855 hover:bg-slate-800 text-emerald-400 hover:text-white"
                          }`}
                        >
                          Approve Override (A)
                        </button>
                        <button
                          type="button"
                          onClick={() => handleConfirmMissing(item)}
                          className={`rounded-lg border px-3.5 py-1.5 text-xs font-bold transition-all duration-150 cursor-pointer ${
                            isConfMissing
                              ? "bg-rose-600 border-rose-500 text-white shadow-sm"
                              : "bg-slate-900 border-slate-855 hover:bg-slate-800 text-rose-400 hover:text-white"
                          }`}
                        >
                          Confirm Missing (M)
                        </button>
                      </div>
                      
                      <div className="flex-1 max-w-sm">
                        <textarea
                          id={`note-${item.item_number}`}
                          rows={1}
                          placeholder="Add Note (N)..."
                          value={noteVal}
                          onChange={(e) => onNoteChange(item.item_number, e.target.value)}
                          className="w-full rounded-lg border border-slate-800 bg-slate-955 px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-violet-500 focus:outline-none transition-colors duration-150 font-medium resize-none"
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Verified OK Collapsed Section */}
        <section className="border border-slate-800/60 bg-slate-900/10 rounded-xl overflow-hidden">
          <button
            id="verified-ok-toggle"
            type="button"
            onClick={() => setIsVerifiedExpanded(prev => !prev)}
            className="flex w-full items-center justify-between px-5 py-4 text-sm font-semibold text-slate-300 hover:text-slate-100 hover:bg-slate-900/30 transition-all cursor-pointer outline-none focus:ring-1 focus:ring-slate-700"
          >
            <span className="flex items-center gap-2">
              <span>Verified OK / N/A</span>
              <span className="rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 text-[11px] font-extrabold font-mono">
                {verifiedOk.length}
              </span>
            </span>
            <span>{isVerifiedExpanded ? "Collapse ▲" : "Expand ▼"}</span>
          </button>
          
          {isVerifiedExpanded && (
            <div className="border-t border-slate-850 divide-y divide-slate-850">
              {verifiedOk.map((item) => (
                <div key={item.item_number} className="px-5 py-3 hover:bg-slate-900/20 flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="min-w-0">
                    <span className="font-semibold text-slate-200">{item.item_number}. {item.document_name}</span>
                    <span className="text-slate-500 font-medium ml-2">({item.confidence_detail})</span>
                  </div>
                  <div className="flex gap-2">
                    <span className="rounded bg-slate-900 border border-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-400">
                      {item.status.replace(/_/g, " ")}
                    </span>
                    <span className="rounded bg-slate-900 border border-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-400">
                      {item.confidence}
                    </span>
                  </div>
                </div>
              ))}
              {verifiedOk.length === 0 && (
                <div className="p-4 text-center text-xs text-slate-500 italic">No verified items.</div>
              )}
            </div>
          )}
        </section>

        {/* Global Submit panel */}
        {exceptions.length > 0 && (
          <div className="border-t border-slate-900 pt-4 flex justify-end gap-3">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={handleSubmit}
              className="rounded-lg bg-violet-600 hover:bg-violet-500 px-6 py-2.5 text-sm font-bold text-white shadow-sm transition-all active:scale-[0.98] disabled:bg-slate-800 disabled:text-slate-500 cursor-pointer border-none"
            >
              {isSubmitting ? "Submitting Decisions..." : "Submit Review Decisions"}
            </button>
          </div>
        )}

        {/* Keyboard shortcuts helper bar */}
        <footer className="rounded-lg border border-slate-900 bg-slate-950/40 px-4 py-3 flex items-center justify-between text-[11px] text-slate-500 font-medium">
          <div className="flex items-center gap-2">
            <span className="bg-slate-900 border border-slate-850 px-1.5 py-0.5 rounded text-slate-400 font-bold">A</span>
            <span>Approve Override</span>
            <span className="mx-1 text-slate-700">·</span>
            <span className="bg-slate-900 border border-slate-850 px-1.5 py-0.5 rounded text-slate-400 font-bold">M</span>
            <span>Confirm Missing</span>
            <span className="mx-1 text-slate-700">·</span>
            <span className="bg-slate-900 border border-slate-850 px-1.5 py-0.5 rounded text-slate-400 font-bold">N</span>
            <span>Add Note</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="bg-slate-900 border border-slate-850 px-1.5 py-0.5 rounded text-slate-400 font-bold">←</span>
            <span className="bg-slate-900 border border-slate-850 px-1.5 py-0.5 rounded text-slate-400 font-bold">→</span>
            <span>Navigate Card</span>
            <span className="mx-1 text-slate-700">·</span>
            <span className="bg-slate-900 border border-slate-850 px-2 py-0.5 rounded text-slate-400 font-bold">Shift+Enter</span>
            <span>Submit Review</span>
          </div>
        </footer>

      </div>
    </section>
  );

  function onNoteChange(itemNumber: number, value: string) {
    setNotes(prev => ({ ...prev, [itemNumber]: value }));
  }
}

function SummaryBlock({
  label,
  count,
  total,
  color,
  border,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
  border: string;
}) {
  return (
    <div className={`rounded-lg border ${border} bg-slate-900/60 px-4.5 py-2.5 min-w-[100px] text-center`}>
      <div className={`text-base font-extrabold ${color}`}>{count}</div>
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500 font-bold mt-0.5">{label}</div>
    </div>
  );
}
