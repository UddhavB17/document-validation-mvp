"use client";

import { useLocale, t } from "@/lib/i18n";

export type OpsStatus = "needs_review" | "clean" | "processing" | "failed";

const STATUS_KEY: Record<OpsStatus, "ops.review.status.needs_review" | "ops.review.status.clean" | "ops.review.status.processing" | "ops.review.status.failed"> = {
  needs_review: "ops.review.status.needs_review",
  clean: "ops.review.status.clean",
  processing: "ops.review.status.processing",
  failed: "ops.review.status.failed",
};

const STATUS_TONE: Record<OpsStatus, string> = {
  needs_review: "bg-amber-100 text-amber-900 border-amber-300",
  clean: "bg-emerald-100 text-emerald-900 border-emerald-300",
  processing: "bg-sky-100 text-sky-900 border-sky-300",
  failed: "bg-red-100 text-red-900 border-red-300",
};

export function normalizeOpsStatus(value: string | null | undefined): OpsStatus {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "clean" || normalized === "processing" || normalized === "failed") {
    return normalized;
  }
  // Legacy reviewer vocabulary (CLEAN / NEEDS_REVIEW / CRITICAL) folds into
  // the ops vocabulary; raw values never reach the pill.
  return "needs_review";
}

export function StatusPill({ status }: { status: string | null | undefined }) {
  const { locale } = useLocale();
  const normalized = normalizeOpsStatus(status);
  return (
    <span
      role="status"
      className={`inline-flex min-h-[28px] items-center rounded-full border px-3 py-1 text-xs font-bold ${STATUS_TONE[normalized]}`}
    >
      {t(locale, STATUS_KEY[normalized])}
    </span>
  );
}
