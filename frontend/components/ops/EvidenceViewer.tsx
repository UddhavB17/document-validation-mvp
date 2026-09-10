"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useLocale, t } from "@/lib/i18n";

import { Bbox, bboxToStyle, severityBoxClass } from "./bbox";

export interface EvidenceSelection {
  page: number;
  pages: number[];
  /** Page the bbox belongs to; null when the selection has no box. */
  evidencePage: number | null;
  bbox: Bbox | null;
  severity: string | null | undefined;
  title: string;
  highlight?: string;
}

export function EvidenceViewer({
  applicationId,
  selection,
  onSelectPage,
  onClose,
}: {
  applicationId: number;
  selection: EvidenceSelection;
  onSelectPage: (page: number) => void;
  onClose: () => void;
}) {
  const { locale } = useLocale();
  const [imageError, setImageError] = useState(false);
  const pages = selection.pages.length > 0 ? selection.pages : [selection.page];
  const activeIndex = Math.max(0, pages.indexOf(selection.page));

  useEffect(() => {
    setImageError(false);
  }, [selection.page, applicationId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const boxStyle = selection.bbox && selection.page === selection.evidencePage ? bboxToStyle(selection.bbox) : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t(locale, "ops.evidence.title")}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{t(locale, "ops.evidence.title")}</p>
            <h2 className="truncate text-sm font-bold text-slate-900">
              {t(locale, "ops.evidence.pageOf")} {selection.page} · {selection.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t(locale, "ops.evidence.close")}
            className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
          >
            {t(locale, "ops.evidence.close")}
          </button>
        </header>

        <a className="border-b px-4 py-2 text-sm font-semibold" href={api.sourcePdfUrl(applicationId, selection.page)} target="_blank" rel="noreferrer">{t(locale, "ops.evidence.fullPdf")}</a>

        {boxStyle === null ? (
          <p role="note" className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-xs font-semibold text-amber-900">
            {t(locale, "ops.evidence.noBox")}
          </p>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto bg-slate-800/10 p-4">
          {imageError ? (
            <p role="alert" className="mx-auto max-w-md rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm font-semibold text-amber-900">
              {t(locale, "ops.review.loadError")}
            </p>
          ) : (
            <div className="relative mx-auto w-fit max-w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                key={`${applicationId}-${selection.page}`}
                src={api.sourcePageImageUrl(applicationId, selection.page, selection.page === selection.evidencePage ? selection.highlight : undefined)}
                alt={`${t(locale, "ops.evidence.pageOf")} ${selection.page}`}
                onError={() => setImageError(true)}
                className="h-auto max-w-full rounded-sm border border-slate-200 bg-white shadow"
              />
              {boxStyle ? (
                <div
                  aria-hidden="true"
                  className={`pointer-events-none absolute rounded-[2px] border-[3px] p-1 ${severityBoxClass(selection.severity)}`}
                  style={boxStyle}
                />
              ) : null}
            </div>
          )}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3">
          <button
            type="button"
            onClick={() => onSelectPage(pages[activeIndex - 1])}
            disabled={activeIndex <= 0}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
          >
            {t(locale, "ops.evidence.previous")}
          </button>
          <span className="text-xs font-semibold text-slate-500">
            {t(locale, "ops.evidence.pageOf")} {selection.page}
          </span>
          <button
            type="button"
            onClick={() => onSelectPage(pages[activeIndex + 1])}
            disabled={activeIndex >= pages.length - 1}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
          >
            {t(locale, "ops.evidence.next")}
          </button>
        </footer>
      </div>
    </div>
  );
}
