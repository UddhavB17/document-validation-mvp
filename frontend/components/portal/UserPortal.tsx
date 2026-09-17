"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { bboxToStyle } from "@/components/ops/bbox";
import { NdcChecklist } from "@/components/ops/NdcChecklist";
import type { OpsApplication } from "@/lib/api";
import { evidenceProxyPageImageUrl } from "@/lib/evidenceProxy";

export type PortalLang = "EN" | "HI";
type PortalView = "dashboard" | "report";

export interface PortalActionItem {
  key: string;
  titleEn: string;
  titleHi: string;
  detailEn: string;
  detailHi: string;
  applicant: string;
  pages: number[];
  tone: "amber" | "rose";
  evidenceBbox: [number, number, number, number] | null;
}

const DEMO_ITEMS: PortalActionItem[] = [
  {
    key: "pan_mismatch",
    titleEn: "PAN Card Name Mismatch",
    titleHi: "पैन कार्ड नाम में भिन्नता",
    detailEn: "Name on uploaded PAN card (Peeru Lal) differs slightly from bank records.",
    detailHi: "अपलोड किए गए पैन कार्ड में नाम बैंक रिकॉर्ड से थोड़ा अलग है।",
    applicant: "Peeru Lal",
    pages: [45],
    tone: "amber",
    evidenceBbox: [0.12, 0.4, 0.55, 0.48],
  },
  {
    key: "disbursement_missing",
    titleEn: "Missing Disbursement Request Form",
    titleHi: "भुगतान अनुरोध फ़ॉर्म गायब है",
    detailEn: "The signed form authorizing loan payment transfer is missing from the file.",
    detailHi: "ऋण राशि ट्रांसफर करने के लिए हस्ताक्षरित फ़ॉर्म गायब है।",
    applicant: "Loan Payout",
    pages: [],
    tone: "rose",
    evidenceBbox: null,
  },
  {
    key: "address_mismatch",
    titleEn: "Address Mismatch (Co-applicant 2)",
    titleHi: "पता भिन्नता (सह-आवेदक 2)",
    detailEn: "Voter ID address for Radha Bai does not match Aadhaar proof.",
    detailHi: "राधा बाई का वोटर आईडी पता आधार कार्ड पते से मेल नहीं खाता।",
    applicant: "Radha Bai",
    pages: [7],
    tone: "amber",
    evidenceBbox: null,
  },
];

function toActionItems(application: OpsApplication | null): PortalActionItem[] {
  if (!application) return DEMO_ITEMS;
  const findings: PortalActionItem[] = application.top_findings.slice(0, 5).map((finding, index) => ({
    key: `${finding.code}-${index}`,
    titleEn: finding.title.en,
    titleHi: finding.title.hi,
    detailEn: finding.detail.en,
    detailHi: finding.detail.hi,
    applicant: application.applicant_name || "Applicant",
    pages: finding.pages,
    tone: finding.severity === "HIGH" ? "rose" : "amber",
    evidenceBbox: finding.evidence?.bbox ?? null,
  }));
  // Pending things are every finding plus every page-to-verify not already
  // covered by a finding, so no actionable page stays hidden behind the
  // backend's 5-finding cap. Page rows are plain amber: re-upload a clear scan.
  const coveredPages = new Set(findings.flatMap((finding) => finding.pages));
  const pageItems: PortalActionItem[] = application.pages_to_verify
    .filter((row) => !coveredPages.has(row.page))
    .map((row) => ({
      key: `page-${row.page}`,
      titleEn: row.document.en,
      titleHi: row.document.hi,
      detailEn: row.problem.en,
      detailHi: row.problem.hi,
      applicant: application.applicant_name || "Applicant",
      pages: [row.page],
      tone: "amber",
      evidenceBbox: null,
    }));
  return [...findings, ...pageItems];
}

function healthRingClass(pct: number): string {
  if (pct >= 90) return "stroke-emerald-500";
  if (pct >= 60) return "stroke-amber-500";
  return "stroke-rose-500";
}

function fixabilityVerdict(
  items: PortalActionItem[],
  lang: PortalLang,
): { label: string; guidance: string; pill: string } {
  const hard = items.filter((item) => item.tone === "rose").length;
  if (items.length === 0) {
    return lang === "EN"
      ? {
          label: "All good — nothing to fix",
          guidance: "Your file looks complete. You may proceed.",
          pill: "border-emerald-300 bg-emerald-100 text-emerald-800",
        }
      : {
          label: "सब सही है — कुछ ठीक नहीं करना",
          guidance: "आपकी फ़ाइल पूरी है। आप आगे बढ़ सकते हैं।",
          pill: "border-emerald-300 bg-emerald-100 text-emerald-800",
        };
  }
  if (hard === 0) {
    return lang === "EN"
      ? {
          label: "🔧 Easy to fix",
          guidance: "Just upload the missing papers — no branch visit needed.",
          pill: "border-emerald-300 bg-emerald-100 text-emerald-800",
        }
      : {
          label: "🔧 ठीक करना आसान",
          guidance: "बस गायब कागज़ अपलोड करें — शाखा जाने की ज़रूरत नहीं।",
          pill: "border-emerald-300 bg-emerald-100 text-emerald-800",
        };
  }
  if (hard * 2 <= items.length) {
    return lang === "EN"
      ? {
          label: "🔧 Mostly easy to fix",
          guidance: `Only ${hard} of ${items.length} may need a branch visit — the rest just need an upload.`,
          pill: "border-amber-300 bg-amber-100 text-amber-800",
        }
      : {
          label: "🔧 अधिकतर आसान",
          guidance: `केवल ${hard} कार्य के लिए शाखा जाना पड़ सकता है — बाकी सिर्फ अपलोड से हो जाएंगे।`,
          pill: "border-amber-300 bg-amber-100 text-amber-800",
        };
  }
  return lang === "EN"
    ? {
        label: "🏦 Needs branch support",
        guidance: "Please visit your branch with your documents — the team will help you fix these.",
        pill: "border-rose-300 bg-rose-100 text-rose-800",
      }
    : {
        label: "🏦 शाखा की मदद चाहिए",
        guidance: "कृपया अपने दस्तावेज़ लेकर शाखा जाएं — टीम आपकी मदद करेगी।",
        pill: "border-rose-300 bg-rose-100 text-rose-800",
      };
}

export function LangButton({
  lang,
  onLangChange,
}: {
  lang: PortalLang;
  onLangChange: (next: PortalLang) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onLangChange(lang === "EN" ? "HI" : "EN")}
      className="rounded-md bg-slate-200 px-2.5 py-1 text-xs font-bold text-slate-700 transition hover:bg-slate-300"
      aria-label="Switch language"
    >
      {lang === "EN" ? "🌐 हिंदी में बदलें" : "🌐 English"}
    </button>
  );
}

export function PortalHeader({
  lang,
  onLangChange,
  meta,
  view,
  onViewChange,
}: {
  lang: PortalLang;
  onLangChange: (next: PortalLang) => void;
  meta: ReactNode;
  view?: PortalView;
  onViewChange?: (next: PortalView) => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-blue-600 px-3 py-1.5 text-lg font-black tracking-wide text-white">DMEF</div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-900">Loan Verification Portal</h1>
            <p className="text-xs text-slate-500">{meta}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {view && onViewChange ? (
            <div className="flex rounded-lg border border-slate-200 bg-slate-100 p-1 text-xs font-medium">
              <button
                type="button"
                onClick={() => onViewChange("dashboard")}
                className={`rounded-md px-3 py-1 transition-all ${view === "dashboard" ? "bg-white font-bold text-blue-600 shadow" : "text-slate-600"}`}
              >
                Dashboard
              </button>
              <button
                type="button"
                onClick={() => onViewChange("report")}
                className={`rounded-md px-3 py-1 transition-all ${view === "report" ? "bg-white font-bold text-blue-600 shadow" : "text-slate-600"}`}
              >
                Fix Document
              </button>
            </div>
          ) : null}
          <LangButton lang={lang} onLangChange={onLangChange} />
        </div>
      </div>
    </header>
  );
}

export function UserPortal({
  application,
  liveProgressPct,
  fallbackId,
  chrome = true,
}: {
  application: OpsApplication | null;
  liveProgressPct?: number | null;
  fallbackId?: number | null;
  /** False when embedded in the ops shell (AppShell provides the chrome). */
  chrome?: boolean;
}) {
  const [view, setView] = useState<PortalView>("dashboard");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [lang, setLang] = useState<PortalLang>("EN");

  const items = useMemo(() => toActionItems(application), [application]);
  const selected = items.find((item) => item.key === selectedKey) ?? null;

  const total = application?.checklist.total ?? 28;
  const found = application?.checklist.found ?? 25;
  const healthPct = total > 0 ? Math.round((found / total) * 100) : 0;
  // While a file is still being checked, show live processing progress.
  // Once checking is done (or status is unknown), show checklist health so
  // the banner and donut agree with the action list below.
  const progress =
    liveProgressPct !== null && liveProgressPct !== undefined && liveProgressPct < 100
      ? liveProgressPct
      : healthPct;

  const appLabel = application
    ? `APP-${String(application.application_id).padStart(4, "0")}`
    : fallbackId
      ? `APP-${String(fallbackId).padStart(4, "0")}`
      : "APP-0004";
  const borrower = application?.applicant_name || "Peeru Lal";
  const loanId = application?.loan_id || "LN-001";
  const summaryEn =
    application?.summary.en ||
    "Your loan file needs 3 small fixes: a PAN name correction, one missing payout form, and an address update. All three are easy to fix.";
  const summaryHi =
    application?.summary.hi ||
    "आपकी ऋण फ़ाइल में 3 छोटे सुधार चाहिए: पैन नाम सुधार, एक गायब भुगतान फ़ॉर्म और पता अद्यतन। तीनों आसानी से ठीक हो जाएंगे।";
  const missing = application?.checklist.missing ?? 3;
  const notChecked = application?.checklist.not_checked ?? 0;
  const portalAppId = application?.application_id ?? fallbackId ?? null;

  const openIssue = (key: string) => {
    setSelectedKey(key);
    setView("report");
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-800">
      {chrome ? (
      <PortalHeader
        lang={lang}
        onLangChange={setLang}
        view={view}
        onViewChange={setView}
        meta={
          <>
            Application ID: <span className="font-mono font-semibold text-slate-700">{appLabel}</span>
            <span className="ml-2 hidden sm:inline">
              Borrower: <span className="font-semibold text-slate-700">{borrower}</span>
            </span>
          </>
        }
      />
      ) : (
        <div className="mx-auto flex max-w-7xl justify-end px-4 pt-4 sm:px-6">
          <LangButton lang={lang} onLangChange={setLang} />
        </div>
      )}

      <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
        {view === "dashboard" ? (
          <DashboardView
            lang={lang}
            items={items}
            progress={progress}
            borrower={borrower}
            loanId={loanId}
            total={total}
            found={found}
            missing={missing}
            notChecked={notChecked}
            summaryEn={summaryEn}
            summaryHi={summaryHi}
            applicationId={portalAppId}
            onFixIssue={openIssue}
          />
        ) : (
          <DocumentReportView
            lang={lang}
            item={selected ?? items[0] ?? DEMO_ITEMS[0]}
            applicationId={application?.application_id ?? fallbackId ?? null}
            onBack={() => setView("dashboard")}
          />
        )}
      </main>
    </div>
  );
}

function DashboardView({
  lang,
  items,
  progress,
  borrower,
  loanId,
  total,
  found,
  missing,
  notChecked,
  summaryEn,
  summaryHi,
  applicationId,
  onFixIssue,
}: {
  lang: PortalLang;
  items: PortalActionItem[];
  progress: number;
  borrower: string;
  loanId: string;
  total: number;
  found: number;
  missing: number;
  notChecked: number;
  summaryEn: string;
  summaryHi: string;
  applicationId: number | null;
  onFixIssue: (key: string) => void;
}) {
  const verdict = fixabilityVerdict(items, lang);
  const ringC = 2 * Math.PI * 52;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 rounded-r-xl border-l-4 border-amber-500 bg-amber-50 p-4 shadow-sm md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span aria-hidden="true" className="mt-0.5 text-xl">⚠️</span>
          <div>
            <h2 className="text-base font-bold text-amber-900">
              {lang === "EN"
                ? `Action Needed: ${items.length} Simple Fixes Required`
                : `ध्यान दें: ${items.length} दस्तावेज़ों में सुधार आवश्यक है`}
            </h2>
            <p className="mt-0.5 text-xs text-amber-700">
              {lang === "EN"
                ? `Your loan file ${loanId} is ${progress}% complete. Fix the items below to finish approval.`
                : `आपकी ऋण फ़ाइल ${loanId} ${progress}% पूरी हो चुकी है। स्वीकृति के लिए नीचे दिए गए दस्तावेज़ सुधारें।`}
            </p>
          </div>
        </div>
        <div className="w-full shrink-0 md:w-48">
          <div className="mb-1 flex justify-between text-xs font-bold text-amber-900">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="h-2.5 w-full rounded-full bg-amber-200" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-2.5 rounded-full bg-amber-600" style={{ width: `${progress}%` }} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{lang === "EN" ? "Borrower" : "आवेदक"}</p>
            <p className="mt-1 text-xl font-black text-slate-900">{borrower}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{loanId}</p>
          </div>
          <div className="rounded-xl bg-blue-50 p-3 text-xl" aria-hidden="true">📄</div>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{lang === "EN" ? "Documents Status" : "दस्तावेज़ स्थिति"}</p>
            <p className="mt-1 text-xl font-black text-emerald-600">{found} / {total} Passed</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{items.length} need attention</p>
          </div>
          <div className="rounded-xl bg-emerald-50 p-3 text-xl" aria-hidden="true">🛡️</div>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{lang === "EN" ? "Pending Actions" : "बकाया कार्य"}</p>
            <p className="mt-1 text-xl font-black text-amber-600">{items.length} Items</p>
            <p className="mt-0.5 text-[11px] font-medium text-amber-700">Requires re-upload</p>
          </div>
          <div className="rounded-xl bg-amber-50 p-3 text-xl" aria-hidden="true">⚠️</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-900">
            <span aria-hidden="true">📋</span>
            {lang === "EN" ? "Report Summary" : "रिपोर्ट सारांश"}
          </h3>
          <p className="text-sm leading-relaxed text-slate-700">{lang === "EN" ? summaryEn : summaryHi}</p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-900">
            <span aria-hidden="true">❤️</span>
            {lang === "EN" ? "File Health" : "फ़ाइल की स्थिति"}
          </h3>
          <div className="flex items-center gap-4">
            <div className="relative h-28 w-28 shrink-0">
              <svg viewBox="0 0 120 120" className="h-28 w-28 -rotate-90" role="img" aria-label={lang === "EN" ? `File health ${progress} percent` : `फ़ाइल की स्थिति ${progress} प्रतिशत`}>
                <circle cx="60" cy="60" r="52" fill="none" strokeWidth="12" className="stroke-slate-200" />
                <circle
                  cx="60"
                  cy="60"
                  r="52"
                  fill="none"
                  strokeWidth="12"
                  strokeLinecap="round"
                  className={healthRingClass(progress)}
                  strokeDasharray={ringC}
                  strokeDashoffset={ringC * (1 - Math.min(100, Math.max(0, progress)) / 100)}
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-xl font-black text-slate-900">{progress}%</span>
              </div>
            </div>
            <ul className="space-y-1.5 text-xs font-medium text-slate-600">
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden="true" />
                {lang === "EN" ? `Passed: ${found}` : `पास: ${found}`}
              </li>
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-500" aria-hidden="true" />
                {lang === "EN" ? `Missing papers: ${missing}` : `गायब कागज़: ${missing}`}
              </li>
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-slate-400" aria-hidden="true" />
                {lang === "EN" ? `Not checked: ${notChecked}` : `जांच लंबित: ${notChecked}`}
              </li>
            </ul>
          </div>
          <div
            className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-slate-200"
            role="img"
            aria-label={lang === "EN" ? `${found} passed, ${missing} missing, ${notChecked} not checked` : `${found} पास, ${missing} गायब, ${notChecked} जांच लंबित`}
          >
            <div className="bg-emerald-500" style={{ width: `${total > 0 ? (found / total) * 100 : 0}%` }} />
            <div className="bg-amber-500" style={{ width: `${total > 0 ? (missing / total) * 100 : 0}%` }} />
            <div className="bg-slate-400" style={{ width: `${total > 0 ? (notChecked / total) * 100 : 0}%` }} />
          </div>
          <div className="mt-3">
            <span className={`inline-block rounded-full border px-2.5 py-1 text-xs font-bold ${verdict.pill}`}>
              {verdict.label}
            </span>
            <p className="mt-1.5 text-xs text-slate-600">{verdict.guidance}</p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <h3 className="mb-4 text-sm font-bold text-slate-900">{lang === "EN" ? "Required Action Items" : "ज़रूरी कार्य जिन्हें पूरा करना है"}</h3>
        {items.length === 0 ? (
          <p className="rounded-lg bg-emerald-50 p-4 text-sm font-medium text-emerald-800">
            {lang === "EN" ? "All clear — no fixes needed. You may proceed." : "सब कुछ सही है — कोई सुधार आवश्यक नहीं।"}
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <div
                key={item.key}
                id={`fix-${item.key}`}
                className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-amber-400 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 shrink-0 rounded-lg p-2.5 text-lg ${item.tone === "rose" ? "bg-rose-100" : "bg-amber-100"}`} aria-hidden="true">
                    {item.tone === "rose" ? "📤" : "📄"}
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-900">{lang === "EN" ? item.titleEn : item.titleHi}</h4>
                    <p className="mt-0.5 text-xs text-slate-600">{lang === "EN" ? item.detailEn : item.detailHi}</p>
                    <p className="mt-1 text-[11px] font-medium text-slate-500">
                      {item.applicant}
                      {item.pages.length > 0 ? ` · Page ${item.pages.join(", ")}` : ""}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onFixIssue(item.key)}
                  className="flex w-full shrink-0 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 sm:w-auto"
                >
                  <span>{lang === "EN" ? "Fix Document" : "दस्तावेज़ सुधारें"}</span>
                  <span aria-hidden="true">→</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {applicationId !== null ? (
        <NdcChecklist applicationId={applicationId} />
      ) : null}
    </div>
  );
}

function DocumentReportView({
  lang,
  item,
  applicationId,
  onBack,
}: {
  lang: PortalLang;
  item: PortalActionItem;
  applicationId: number | null;
  onBack: () => void;
}) {
  // Real page render when we know the application and page; otherwise (or
  // when the render fails, e.g. logged-out demo) fall back to the mock box.
  const [imgFailed, setImgFailed] = useState(false);
  const [imgLoading, setImgLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    setImgFailed(false);
    setImgLoading(true);
    setZoom(1);
    setRotation(0);
  }, [item.key]);
  const pageNo = item.pages.length > 0 ? item.pages[0] : null;
  const showPreview = applicationId !== null && pageNo !== null && !imgFailed;

  function reloadImage(): void {
    setImgFailed(false);
    setImgLoading(true);
    setReloadKey((key) => key + 1);
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-600 shadow-sm transition hover:text-slate-900"
        >
          <span aria-hidden="true" className="mr-1.5">←</span>
          {lang === "EN" ? "Back to Dashboard" : "डैशबोर्ड पर वापस जाएं"}
        </button>
        <span className="text-xs font-semibold text-slate-500">
          {item.pages.length > 0 ? `Page ${item.pages[0]}` : lang === "EN" ? "Document review" : "दस्तावेज़ समीक्षा"}
        </span>
      </div>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm lg:col-span-7">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700">
              {lang === "EN" ? "Uploaded Document" : "स्कैन किया गया दस्तावेज़"}
            </h3>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setZoom((z) => Math.max(1, Math.round((z - 0.5) * 10) / 10))}
                disabled={zoom <= 1}
                title={lang === "EN" ? "Zoom out" : "छोटा करें"}
                aria-label={lang === "EN" ? "Zoom out" : "छोटा करें"}
                className="rounded bg-slate-100 p-1.5 text-xs transition hover:bg-slate-200 disabled:opacity-40"
              >
                <span aria-hidden="true">🔍−</span>
              </button>
              <span className="min-w-10 text-center font-mono text-[11px] font-bold text-slate-500" aria-live="polite">
                {Math.round(zoom * 100)}%
              </span>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.min(3, Math.round((z + 0.5) * 10) / 10))}
                disabled={zoom >= 3}
                title={lang === "EN" ? "Zoom in" : "बड़ा करें"}
                aria-label={lang === "EN" ? "Zoom in" : "बड़ा करें"}
                className="rounded bg-slate-100 p-1.5 text-xs transition hover:bg-slate-200 disabled:opacity-40"
              >
                <span aria-hidden="true">🔍+</span>
              </button>
              <button
                type="button"
                onClick={() => setRotation((r) => (r + 90) % 360)}
                title={lang === "EN" ? "Rotate 90 degrees" : "90 डिग्री घुमाएँ"}
                aria-label={lang === "EN" ? "Rotate 90 degrees" : "90 डिग्री घुमाएँ"}
                className="rounded bg-slate-100 p-1.5 text-xs transition hover:bg-slate-200"
              >
                <span aria-hidden="true" className="inline-block" style={{ transform: `rotate(${rotation}deg)` }}>↻</span>
              </button>
              <button
                type="button"
                onClick={reloadImage}
                disabled={applicationId === null}
                title={lang === "EN" ? "Reload image" : "तस्वीर फिर से लोड करें"}
                aria-label={lang === "EN" ? "Reload image" : "तस्वीर फिर से लोड करें"}
                className="rounded bg-slate-100 p-1.5 text-xs transition hover:bg-slate-200 disabled:opacity-40"
              >
                <span aria-hidden="true">⟳</span>
              </button>
            </div>
          </div>

          <div className="relative overflow-auto rounded-lg border border-slate-300 bg-slate-100" style={{ maxHeight: 560 }}>
            <div
              className="relative mx-auto"
              style={{
                width: `${zoom * 100}%`,
                maxWidth: zoom > 1 ? "none" : undefined,
                transform: rotation ? `rotate(${rotation}deg)` : undefined,
              }}
            >
          {showPreview && applicationId !== null && pageNo !== null ? (
            <>
              {imgLoading ? (
                <div
                  className="flex min-h-[280px] items-center justify-center gap-2 p-8 text-sm font-medium text-slate-500"
                  role="status"
                >
                  <span
                    className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600"
                    aria-hidden="true"
                  />
                  {lang === "EN" ? "Loading page…" : "पृष्ठ लोड हो रहा है…"}
                </div>
              ) : null}
              <img
                key={`${applicationId}-${pageNo}-${reloadKey}`}
                src={evidenceProxyPageImageUrl(applicationId, pageNo)}
                onLoad={() => setImgLoading(false)}
                onError={() => {
                  setImgFailed(true);
                  setImgLoading(false);
                }}
                alt={lang === "EN" ? `Scanned page ${pageNo}` : `स्कैन किया गया पृष्ठ ${pageNo}`}
                className="w-full"
                style={{ display: imgLoading ? "none" : undefined }}
              />
              {!imgLoading && item.evidenceBbox ? (
                <div
                  className="pointer-events-none absolute rounded border-[3px] border-rose-600 bg-rose-500/10"
                  style={bboxToStyle(item.evidenceBbox)}
                  aria-hidden="true"
                />
              ) : null}
            </>
          ) : (
          <div className="relative flex min-h-[280px] items-center justify-center overflow-hidden rounded-lg border border-slate-300 bg-slate-900 p-4">
            <div className="relative w-full max-w-md space-y-3 rounded-lg border-2 border-blue-600 bg-amber-100/90 p-4 text-slate-900 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-400 pb-2 text-[10px] font-bold uppercase tracking-wider">
                <span>{lang === "EN" ? item.titleEn : item.titleHi}</span>
                <span>{item.pages.length > 0 ? `P-${item.pages[0]}` : "DOC"}</span>
              </div>
              <p className="text-xs leading-relaxed">{lang === "EN" ? item.detailEn : item.detailHi}</p>
              {item.evidenceBbox ? (
                <div
                  className="pointer-events-none absolute rounded border-2 border-rose-600 bg-rose-500/10"
                  style={{
                    left: `${item.evidenceBbox[0] * 100}%`,
                    top: `${item.evidenceBbox[1] * 100}%`,
                    width: `${Math.max(8, (item.evidenceBbox[2] - item.evidenceBbox[0]) * 100)}%`,
                    height: `${Math.max(8, (item.evidenceBbox[3] - item.evidenceBbox[1]) * 100)}%`,
                  }}
                  aria-hidden="true"
                />
              ) : null}
              <div className="absolute right-2 top-2 animate-pulse rounded-full bg-rose-600 px-2 py-0.5 text-[10px] font-bold text-white shadow">
                {lang === "EN" ? "Mismatch highlighted" : "भिन्नता चिह्नित"}
              </div>
            </div>
          </div>
          )}
            </div>
          </div>
          <p className="text-center text-[11px] text-slate-500">
            {lang === "EN" ? "Upload a clear original photo — blurry scans are rejected." : "स्पष्ट मूल फोटो अपलोड करें — धुंधले स्कैन स्वीकार नहीं होंगे।"}
          </p>
        </div>

        <div className="space-y-4 lg:col-span-5">
          <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="rounded-full border border-amber-300 bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-800">
                🟡 {lang === "EN" ? "Action Needed" : "सुधार आवश्यक"}
              </span>
              <span className="font-mono text-xs text-slate-500">{item.applicant}</span>
            </div>

            <div>
              <h3 className="text-base font-bold text-slate-900">{lang === "EN" ? "What needs to be fixed?" : "क्या सुधार करना है?"}</h3>
              <p className="mt-1 text-xs leading-relaxed text-slate-600">{lang === "EN" ? item.detailEn : item.detailHi}</p>
            </div>

            <div className="space-y-2 rounded-lg border border-blue-200 bg-blue-50/70 p-3">
              <p className="flex items-center gap-1 text-xs font-bold text-blue-900">
                <span aria-hidden="true">❓</span>
                {lang === "EN" ? "How to resolve this easily:" : "इसे आसानी से कैसे हल करें:"}
              </p>
              <ul className="list-inside list-disc space-y-1 text-xs text-blue-800">
                <li>{lang === "EN" ? "Upload a clear original photo of the document." : "दस्तावेज़ की स्पष्ट मूल फोटो अपलोड करें।"}</li>
                <li>{lang === "EN" ? "If the name differs, add a name affidavit (नाम शपथ पत्र)." : "यदि नाम अलग है, तो नाम शपथ पत्र जोड़ें।"}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
