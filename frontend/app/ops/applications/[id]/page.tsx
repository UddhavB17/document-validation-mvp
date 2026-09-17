"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { ErrorMessage, LoadingMessage } from "@/components/Message";
import { UserPortal } from "@/components/portal/UserPortal";
import { statusProgressPercentage } from "@/components/ops/opsUtils";
import { normalizeOpsStatus } from "@/components/ops/StatusPill";
import { t, useLocale } from "@/lib/i18n";
import { isApplicationReviewPollingStatus, useApplicationStatus, useOpsApplication } from "@/lib/queries";

export default function OpsApplicationPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const isValid = Number.isInteger(applicationId) && applicationId > 0;
  const { locale } = useLocale();
  const ops = useOpsApplication(isValid ? applicationId : null);
  const status = useApplicationStatus(isValid ? applicationId : null);
  const wasProcessing = useRef(false);

  const liveStatus = status.data?.status ?? ops.data?.status;
  const processing = normalizeOpsStatus(liveStatus) === "processing";

  useEffect(() => {
    if (processing) {
      wasProcessing.current = true;
    }
  }, [processing]);

  // Refetch the payload once the lightweight status turns terminal. When the
  // status endpoint is unreachable the page keeps the last payload.
  useEffect(() => {
    if (wasProcessing.current && liveStatus && !isApplicationReviewPollingStatus(liveStatus)) {
      wasProcessing.current = false;
      void ops.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  if (!isValid) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <Link href="/ops" className="text-sm font-bold text-brand-primary hover:underline">
          {t(locale, "ops.review.back")}
        </Link>
      </div>
    );
  }

  if (ops.isLoading) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <LoadingMessage message={t(locale, "ops.review.loading")} />
      </div>
    );
  }

  if (ops.isError || !ops.data) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => void ops.refetch()}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
          >
            {t(locale, "ops.common.retry")}
          </button>
          <Link href="/ops" className="rounded-lg px-4 py-2 text-sm font-bold text-brand-primary hover:underline">
            {t(locale, "ops.review.back")}
          </Link>
        </div>
      </div>
    );
  }

  // While in-flight the progress follows the lightweight /status value nested
  // under progress; the full ops payload is fetched once, never polled.
  const statusPercentage = statusProgressPercentage(status.data);
  const progress = statusPercentage ?? ops.data.processing.percentage ?? null;

  return (
    <UserPortal
      chrome={false}
      application={ops.data}
      liveProgressPct={typeof progress === "number" ? progress : null}
      fallbackId={applicationId}
    />
  );
}
