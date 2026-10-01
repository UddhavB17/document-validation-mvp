"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { LoadingMessage } from "@/components/Message";
import { statusProgressPercentage } from "@/components/ops/opsUtils";
import { normalizeOpsStatus } from "@/components/ops/StatusPill";
import { UserPortal, type PortalView } from "@/components/portal/UserPortal";
import { ReviewerCrumb, ReviewerShell } from "@/components/review/ReviewerShell";
import { portalApplicationHref, portalViewFromSearch } from "@/lib/portalNavigation";
import {
  isApplicationReviewPollingStatus,
  useApplicationStatus,
  useCompleteOpsReviewItems,
  useOpsApplication,
  useOpsReviewItems,
} from "@/lib/queries";

function ReviewApplicationContent() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const applicationId = Number(params.id);
  const isValid = Number.isInteger(applicationId) && applicationId > 0;
  const ops = useOpsApplication(isValid ? applicationId : null);
  const status = useApplicationStatus(isValid ? applicationId : null);
  const reviewItems = useOpsReviewItems(isValid ? applicationId : null);
  const completeReview = useCompleteOpsReviewItems(isValid ? applicationId : 0);
  const wasProcessing = useRef(false);
  const selectedKey = searchParams.get("exception");
  const view: PortalView = portalViewFromSearch(searchParams);
  const [note, setNote] = useState("");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const navigate = useCallback(
    (next: { view: PortalView; selectedKey?: string | null }) => {
      router.push(portalApplicationHref(applicationId, searchParams.toString(), next, "/review"));
    },
    [applicationId, router, searchParams],
  );

  const liveStatus = status.data?.status ?? ops.data?.status;
  const processing = normalizeOpsStatus(liveStatus) === "processing";
  const pendingCount = reviewItems.data?.counts.pending ?? 0;

  useEffect(() => {
    if (processing) wasProcessing.current = true;
  }, [processing]);

  useEffect(() => {
    if (wasProcessing.current && liveStatus && !isApplicationReviewPollingStatus(liveStatus)) {
      wasProcessing.current = false;
      void ops.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  if (!isValid) {
    return (
      <ReviewerShell>
        <div className="reviewer-empty" role="alert">
          <p className="reviewer-empty__title">This review link is not valid</p>
          <p className="reviewer-empty__body">
            Go back to the queue and open a file from the list.
          </p>
          <div style={{ marginTop: "1rem" }}>
            <Link href="/review" className="reviewer-btn reviewer-btn--ghost">
              Back to queue
            </Link>
          </div>
        </div>
      </ReviewerShell>
    );
  }

  if (ops.isLoading) {
    return (
      <ReviewerShell
        crumb={
          <ReviewerCrumb
            items={[
              { label: "Queue", href: "/review?tab=queue" },
              { label: "Loading file" },
            ]}
          />
        }
      >
        <LoadingMessage message="Loading file for review..." />
      </ReviewerShell>
    );
  }

  if (ops.isError || !ops.data) {
    return (
      <ReviewerShell
        crumb={
          <ReviewerCrumb
            items={[
              { label: "Queue", href: "/review?tab=queue" },
              { label: "Unavailable" },
            ]}
          />
        }
      >
        <div className="reviewer-empty" role="alert">
          <p className="reviewer-empty__title">Could not load this file</p>
          <p className="reviewer-empty__body">
            The cloud database did not return this application. Return to the queue and try another
            file.
          </p>
          <div style={{ marginTop: "1rem" }}>
            <Link href="/review" className="reviewer-btn reviewer-btn--ghost">
              Back to queue
            </Link>
          </div>
        </div>
      </ReviewerShell>
    );
  }

  const statusPercentage = statusProgressPercentage(status.data);
  const progress = statusPercentage ?? ops.data.processing.percentage ?? null;
  const borrower = ops.data.applicant_name || "Applicant";
  const loanId = ops.data.loan_id || "No loan id";

  return (
    <div className="reviewer">
      <div className="reviewer__frame">
        <ReviewerCrumb
          items={[
            { label: "Saved reviews", href: "/review" },
            { label: "Queue", href: "/review?tab=queue" },
            { label: borrower },
          ]}
        />
        <p className="reviewer__kicker">Open file</p>
        <h1 className="reviewer__title">{borrower}</h1>
        <p className="reviewer__lede">
          {loanId}. Review pending findings below, then save everything you verified on this file.
        </p>

        <div className="reviewer-filebar">
          <div>
            <p className="reviewer-filebar__label">Current place</p>
            <h2 className="reviewer-filebar__title">File review</h2>
            <p className="reviewer-filebar__note">
              {pendingCount} pending finding{pendingCount === 1 ? "" : "s"} still need a save.
            </p>
          </div>
          <div>
            <label className="reviewer-filebar__label" htmlFor="complete-note">
              Shared note for this save
            </label>
            <textarea
              id="complete-note"
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="What did you verify on this file?"
            />
            <div className="reviewer-filebar__actions">
              <button
                type="button"
                className="reviewer-btn reviewer-btn--success"
                disabled={completeReview.isPending || pendingCount === 0}
                onClick={() => {
                  setSaveError(null);
                  setSaveMessage(null);
                  void completeReview
                    .mutateAsync({ note: note.trim() || undefined })
                    .then((result) => {
                      setSaveMessage(
                        `Saved ${result.saved_count} finding${result.saved_count === 1 ? "" : "s"}.`,
                      );
                      navigate({ view: "reviewed", selectedKey: null });
                    })
                    .catch((error: unknown) => {
                      setSaveError(
                        error instanceof Error ? error.message : "Could not save findings.",
                      );
                    });
                }}
              >
                {completeReview.isPending ? "Saving..." : "Save all findings"}
              </button>
              <Link href="/review" className="reviewer-btn reviewer-btn--ghost">
                Back to queue
              </Link>
            </div>
            {saveMessage ? (
              <p className="reviewer-status reviewer-status--ok" role="status">
                {saveMessage}
              </p>
            ) : null}
            {saveError ? (
              <p className="reviewer-status reviewer-status--err" role="alert">
                {saveError}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <UserPortal
        chrome={false}
        application={ops.data}
        liveProgressPct={typeof progress === "number" ? progress : null}
        fallbackId={applicationId}
        navigation={{ view, selectedKey, onNavigate: navigate }}
      />
    </div>
  );
}

export default function ReviewApplicationPage() {
  return (
    <Suspense
      fallback={
        <ReviewerShell>
          <LoadingMessage message="Loading reviewer workspace..." />
        </ReviewerShell>
      }
    >
      <ReviewApplicationContent />
    </Suspense>
  );
}
