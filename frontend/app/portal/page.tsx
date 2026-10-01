"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PortalWorklist } from "@/components/portal/PortalWorklist";
import { UserPortal } from "@/components/portal/UserPortal";
import { ReviewerCrumb, ReviewerShell } from "@/components/review/ReviewerShell";
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
    typeof statusQuery.data?.progress?.percentage === "number"
      ? statusQuery.data.progress.percentage
      : null;

  if (opsQuery.isLoading) {
    return (
      <ReviewerShell
        kicker="My files"
        title="Loading loan file"
        lede="Fetching the latest summary for this application."
        crumb={
          <ReviewerCrumb
            items={[
              { label: "My files", href: "/portal" },
              { label: "Loading file" },
            ]}
          />
        }
      >
        <div className="reviewer-empty" role="status">
          <p className="reviewer-empty__title">Loading your loan file</p>
          <p className="reviewer-empty__body">Fetching the latest summary for this application.</p>
        </div>
      </ReviewerShell>
    );
  }

  if (opsQuery.isError) {
    return (
      <ReviewerShell
        kicker="My files"
        title="Loan file unavailable"
        lede="We could not load this application. You can still browse the sample layout below."
        crumb={
          <ReviewerCrumb
            items={[
              { label: "My files", href: "/portal" },
              { label: "Unavailable" },
            ]}
          />
        }
      >
        <div className="reviewer-empty" role="alert">
          <p className="reviewer-empty__title">Could not load this loan file</p>
          <p className="reviewer-empty__body">
            Showing a sample view so you can still explore the layout.
          </p>
          <div style={{ marginTop: "1rem" }}>
            <Link href="/portal" className="reviewer-btn reviewer-btn--ghost">
              Back to my files
            </Link>
          </div>
        </div>
        <UserPortal
          application={null}
          liveProgressPct={null}
          fallbackId={applicationId}
          chrome={false}
        />
      </ReviewerShell>
    );
  }

  const borrower = opsQuery.data?.applicant_name || "Applicant";

  return (
    <div className="reviewer">
      <div className="reviewer__frame" style={{ paddingBottom: "0.5rem" }}>
        <ReviewerCrumb
          items={[
            { label: "My files", href: "/portal" },
            { label: borrower },
          ]}
        />
        <p className="reviewer__kicker">My files</p>
        <h1 className="reviewer__title">{borrower}</h1>
        <p className="reviewer__lede">
          A clear view of what this loan file still needs. Use Pending and Saved to move through the
          work.
        </p>
      </div>
      <UserPortal
        application={opsQuery.data ?? null}
        liveProgressPct={progressPct}
        fallbackId={applicationId}
        chrome={false}
      />
    </div>
  );
}

export default function PortalPage() {
  return (
    <Suspense
      fallback={
        <ReviewerShell>
          <div className="reviewer-empty" role="status">
            <p className="reviewer-empty__title">Loading</p>
            <p className="reviewer-empty__body">Preparing your files.</p>
          </div>
        </ReviewerShell>
      }
    >
      <PortalContent />
    </Suspense>
  );
}
