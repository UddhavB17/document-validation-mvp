"use client";

import { useState } from "react";

import type { OpsWorklistItem } from "@/lib/api";
import { usePortalWorklist } from "@/lib/queries";

import { LangButton, PortalHeader, type PortalLang } from "./UserPortal";

const DEMO_WORKLIST: OpsWorklistItem[] = [
  { application_id: 4, loan_id: "LN-001", applicant_name: "Peeru Lal", status: "needs_review", findings_count: 3 },
  { application_id: 3, loan_id: "LN-002", applicant_name: "Unkar Lal", status: "clean", findings_count: 0 },
  { application_id: 5, loan_id: "LN-003", applicant_name: "Radha Bai", status: "needs_review", findings_count: 1 },
];

function statusMeta(status: OpsWorklistItem["status"], lang: PortalLang): { label: string; pill: string } {
  switch (status) {
    case "clean":
      return {
        label: lang === "EN" ? "🟢 Looks good" : "🟢 सब सही",
        pill: "border-emerald-300 bg-emerald-100 text-emerald-800",
      };
    case "processing":
      return {
        label: lang === "EN" ? "🔵 Checking…" : "🔵 जांच चल रही…",
        pill: "border-blue-300 bg-blue-100 text-blue-800",
      };
    case "failed":
      return {
        label: lang === "EN" ? "🔴 Needs branch help" : "🔴 शाखा मदद",
        pill: "border-rose-300 bg-rose-100 text-rose-800",
      };
    case "needs_review":
    default:
      return {
        label: lang === "EN" ? "🟡 Needs fix" : "🟡 सुधार आवश्यक",
        pill: "border-amber-300 bg-amber-100 text-amber-800",
      };
  }
}

function appLabel(applicationId: number): string {
  return `APP-${String(applicationId).padStart(4, "0")}`;
}

export function PortalWorklist({
  onOpen,
  chrome = true,
}: {
  onOpen: (applicationId: number) => void;
  /** False when embedded in the ops shell (AppShell provides the chrome). */
  chrome?: boolean;
}) {
  const [lang, setLang] = useState<PortalLang>("EN");
  const worklist = usePortalWorklist();

  const liveRows = worklist.data?.applications ?? [];
  const rows = liveRows.length > 0 || worklist.isLoading ? liveRows : DEMO_WORKLIST;

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-800">
      {chrome ? (
      <PortalHeader
        lang={lang}
        onLangChange={setLang}
        meta={lang === "EN" ? "Your loan files" : "आपकी ऋण फ़ाइलें"}
      />
      ) : (
        <div className="mx-auto flex max-w-3xl justify-end px-4 pt-4 sm:px-6">
          <LangButton lang={lang} onLangChange={setLang} />
        </div>
      )}

      <main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
        <div>
          <h2 className="text-lg font-black text-slate-900">
            {lang === "EN" ? "Choose your loan file" : "अपनी ऋण फ़ाइल चुनें"}
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {lang === "EN"
              ? "Tap a file below to see what needs fixing."
              : "क्या सुधारना है — यह देखने के लिए नीचे किसी फ़ाइल पर टैप करें।"}
          </p>
        </div>

        {worklist.isLoading ? (
          <p role="status" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
            {lang === "EN" ? "Loading your loan files…" : "आपकी ऋण फ़ाइलें लोड हो रही हैं…"}
          </p>
        ) : rows.length === 0 ? (
          <p role="status" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
            {lang === "EN" ? "No loan files found." : "कोई ऋण फ़ाइल नहीं मिली।"}
          </p>
        ) : (
          <ul className="space-y-3">
            {rows.map((item) => {
              const meta = statusMeta(item.status, lang);
              return (
                <li key={item.application_id}>
                  <button
                    type="button"
                    onClick={() => onOpen(item.application_id)}
                    className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-blue-400"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-slate-900">
                        {item.applicant_name || (lang === "EN" ? "Applicant" : "आवेदक")}
                      </p>
                      <p className="mt-0.5 font-mono text-xs font-semibold text-slate-500">
                        {appLabel(item.application_id)}
                        {item.loan_id ? ` · ${item.loan_id}` : ""}
                        {item.findings_count > 0
                          ? ` · ${item.findings_count} ${lang === "EN" ? "fixes" : "सुधार"}`
                          : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${meta.pill}`}>
                        {meta.label}
                      </span>
                      <span aria-hidden="true" className="font-bold text-slate-400">→</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </div>
  );
}
