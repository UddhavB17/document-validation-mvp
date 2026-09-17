"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PortalWorklist } from "@/components/portal/PortalWorklist";
import { UserPortal } from "@/components/portal/UserPortal";
import { usePortalApplication, usePortalStatus } from "@/lib/queries";

function PortalContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const rawApp = searchParams.get("app");
  const parsedApp =
    rawApp !== null && rawApp !== "" && Number.isInteger(Number(rawApp)) && Number(rawApp) > 0
      ? Number(rawApp)
      : null;

  if (parsedApp === null) {
    return <PortalWorklist onOpen={(applicationId) => router.push(`/portal?app=${applicationId}`)} />;
  }
  return <PortalDetail applicationId={parsedApp} />;
}

function PortalDetail({ applicationId }: { applicationId: number }) {
  const opsQuery = usePortalApplication(applicationId);
  const statusQuery = usePortalStatus(applicationId);

  const progressPct =
    typeof statusQuery.data?.progress?.percentage === "number" ? statusQuery.data.progress.percentage : null;

  if (opsQuery.isLoading) {
    return (
      <main className="mx-auto max-w-7xl p-6">
        <p role="status" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
          Loading your loan file…
        </p>
      </main>
    );
  }

  if (opsQuery.isError) {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6">
        <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800">
          Could not load this loan file. Showing the sample view instead.
        </p>
        <UserPortal application={null} liveProgressPct={null} fallbackId={applicationId} />
      </main>
    );
  }

  return <UserPortal application={opsQuery.data ?? null} liveProgressPct={progressPct} fallbackId={applicationId} />;
}

export default function PortalPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6"><p role="status">Loading…</p></main>}>
      <PortalContent />
    </Suspense>
  );
}
