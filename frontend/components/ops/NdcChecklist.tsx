"use client";

import { useMemo, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { ApiError } from "@/lib/api";
import type { NdcRow } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { t, useLocale } from "@/lib/i18n";
import { useCreateDecision, useNdcState, useSetNdcCheck } from "@/lib/queries";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to save. Please try again.";
}

function printChecklist(): void {
  document.body.classList.add("printing-ndc");
  const done = () => {
    document.body.classList.remove("printing-ndc");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

function TickCell({
  label,
  checked,
  byName,
  disabled,
  readOnly,
  onChange,
}: {
  label: string;
  checked: boolean;
  byName: string;
  disabled: boolean;
  readOnly: boolean;
  onChange: (next: boolean) => void;
}) {
  if (readOnly) {
    return (
      <div className="flex flex-col items-center gap-1">
        {checked ? (
          <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-black text-emerald-800">
            ✓
          </span>
        ) : (
          <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-black text-slate-400">
            ○
          </span>
        )}
        {byName ? <span className="max-w-[7rem] truncate text-[10px] text-slate-500">{byName}</span> : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-1">
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-5 w-5 shrink-0 accent-emerald-700"
      />
      {byName ? <span className="max-w-[7rem] truncate text-[10px] text-slate-500">{byName}</span> : null}
    </div>
  );
}

export function NdcChecklist({
  applicationId,
  interactive = true,
}: {
  applicationId: number;
  /** Borrower view: status list without tick boxes or verify/print actions. */
  interactive?: boolean;
}) {
  const { locale } = useLocale();
  const session = useSession();
  const queryClient = useQueryClient();
  // Outside staff login the authenticated fetch would bounce to /login, so
  // the borrower view only loads for authenticated sessions and otherwise
  // renders nothing (no request, no redirect).
  const ndc = useNdcState(!interactive && session.status !== "authenticated" ? null : applicationId);
  const setCheck = useSetNdcCheck(applicationId);
  const createDecision = useCreateDecision(applicationId);
  const [actionError, setActionError] = useState<string | null>(null);

  const groups = useMemo(() => {
    const rows = ndc.data?.rows ?? [];
    const ordered: Array<{ name: string; rows: NdcRow[] }> = [];
    for (const row of rows) {
      const last = ordered[ordered.length - 1];
      if (last && last.name === row.group) {
        last.rows.push(row);
      } else {
        ordered.push({ name: row.group, rows: [row] });
      }
    }
    return ordered;
  }, [ndc.data]);

  if (!interactive && session.status !== "authenticated") {
    return null;
  }

  if (ndc.isLoading) {
    return (
      <section aria-label={t(locale, "ops.ndc.title")} className="space-y-3">
        <LoadingMessage message={t(locale, "ops.review.loading")} />
      </section>
    );
  }

  if (ndc.isError || !ndc.data) {
    return (
      <section aria-label={t(locale, "ops.ndc.title")} className="space-y-3">
        <ErrorMessage message={t(locale, "ops.ndc.loadError")} />
        <button
          type="button"
          onClick={() => void ndc.refetch()}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50"
        >
          {t(locale, "ops.common.retry")}
        </button>
      </section>
    );
  }

  const data = ndc.data;
  const busy = setCheck.isPending || createDecision.isPending;
  const today = new Date().toLocaleDateString(locale === "hi" ? "hi-IN" : "en-IN");

  async function toggleCheck(sNo: number, role: string, checked: boolean): Promise<void> {
    setActionError(null);
    try {
      await setCheck.mutateAsync({ s_no: sNo, role, checked });
    } catch (error) {
      if (error instanceof TypeError) {
        // The request never reached the backend (down, restarting, offline).
        setActionError(t(locale, "ops.ndc.offline"));
      } else if (error instanceof ApiError && error.status === 404) {
        // Stale backend without the /ndc endpoints.
        setActionError(t(locale, "ops.ndc.noService"));
      } else {
        setActionError(errorText(error));
      }
    }
  }

  async function markVerified(): Promise<void> {
    setActionError(null);
    const note =
      `NDC checklist ${data.complete_count}/${data.total} complete ` +
      `(${data.version}). Verified from the ops checklist.`;
    try {
      await createDecision.mutateAsync({
        application_id: applicationId,
        decision: "ACCEPT",
        reviewer_note: note,
      });
      await queryClient.invalidateQueries({ queryKey: ["ndcState", applicationId] });
      await ndc.refetch();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setActionError(t(locale, "ops.ndc.needProcessing"));
      } else {
        setActionError(errorText(error));
      }
    }
  }

  return (
    <section aria-labelledby="ndc-heading" id="ndc-print-root" className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="ndc-heading" className="text-base font-bold text-slate-900">
              {t(locale, "ops.ndc.title")}
            </h2>
            <p className="mt-0.5 font-mono text-xs text-slate-500">{data.version}</p>
            <p className="mt-1 text-xs text-slate-600">
              {interactive ? t(locale, "ops.ndc.howTo") : t(locale, "ops.ndc.readOnlyNote")}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-sm font-black text-slate-900">
              {data.complete_count} / {data.total} {t(locale, "ops.ndc.progress")}
            </p>
            <div
              className="mt-2 h-2.5 w-44 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-valuenow={data.complete_count}
              aria-valuemin={0}
              aria-valuemax={data.total}
            >
              <div
                className="h-full rounded-full bg-emerald-600 transition-all"
                style={{ width: `${data.total > 0 ? (data.complete_count / data.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        </div>

        <div className="ndc-print-header hidden print:mt-4 print:block">
          <p className="text-sm text-slate-700">
            APP-{String(data.application_id).padStart(4, "0")} · {data.applicant_name || "—"} ·{" "}
            {data.loan_id || "—"} · {today}
          </p>
          {data.verified ? (
            <p className="mt-1 text-sm font-black text-emerald-700">VERIFIED ✓</p>
          ) : null}
        </div>

        <div className="mt-4 space-y-5">
          {groups.map((group) => (
            <div key={group.name}>
              <h3 className="mb-2 text-xs font-black uppercase tracking-wider text-slate-500">
                {group.name}
              </h3>
              <ul className="space-y-2">
                {group.rows.map((row) => (
                  <li
                    key={row.s_no}
                    className={`rounded-lg border p-3 ${row.complete ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 bg-white"}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="w-7 shrink-0 pt-0.5 text-center font-mono text-xs font-bold text-slate-500">
                        {row.s_no}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-bold text-slate-900">{row.title}</p>
                        {row.mode !== "—" ? (
                          <p className="mt-0.5 text-[11px] text-slate-500">{row.mode}</p>
                        ) : null}
                        {row.hint ? (
                          <p className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-800">
                            {t(locale, "ops.ndc.manualTag")}: {row.hint}
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 border-t border-slate-100 pt-2 text-center">
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                          {t(locale, "ops.ndc.colSystem")}
                        </p>
                        {row.system_checked ? (
                          <span
                            className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-black text-emerald-800"
                            title={t(locale, "ops.ndc.systemChecked")}
                          >
                            ✓
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400" title={t(locale, "ops.ndc.systemPending")}>
                            —
                          </span>
                        )}
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                          {t(locale, "ops.ndc.colCso")}
                        </p>
                        <TickCell
                          label={`${row.title} CSO BOPS`}
                          checked={row.checks.cso.checked}
                          byName={row.checks.cso.by_name}
                          disabled={busy}
                          readOnly={!interactive}
                          onChange={(next) => void toggleCheck(row.s_no, "cso", next)}
                        />
                      </div>
                      <div>
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                          {t(locale, "ops.ndc.colCops")}
                        </p>
                        <TickCell
                          label={`${row.title} COPS`}
                          checked={row.checks.cops.checked}
                          byName={row.checks.cops.by_name}
                          disabled={busy}
                          readOnly={!interactive}
                          onChange={(next) => void toggleCheck(row.s_no, "cops", next)}
                        />
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {actionError ? (
          <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-900">
            {actionError}
          </p>
        ) : null}

        {interactive ? (
        <div className="ndc-no-print mt-4 flex flex-wrap items-center gap-3">
          {data.verified ? (
            <InfoBanner message={t(locale, "ops.ndc.verifiedNote")} />
          ) : data.complete ? (
            <p className="text-sm font-semibold text-emerald-800">{t(locale, "ops.ndc.allDone")}</p>
          ) : null}
          <button
            type="button"
            onClick={printChecklist}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-bold text-white hover:bg-slate-700"
          >
            🖨 {t(locale, "ops.ndc.print")}
          </button>
          {!data.verified && data.complete ? (
            <button
              type="button"
              onClick={() => void markVerified()}
              disabled={busy}
              className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-600 disabled:opacity-50"
            >
              {createDecision.isPending ? t(locale, "ops.ndc.verifying") : `✓ ${t(locale, "ops.ndc.markVerified")}`}
            </button>
          ) : null}
        </div>
        ) : null}
      </div>
    </section>
  );
}

function InfoBanner({ message }: { message: string }) {
  return (
    <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800">
      {message}
    </p>
  );
}
