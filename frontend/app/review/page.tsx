"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { ReviewQueue } from "@/components/review/ReviewQueue";
import { ReviewerShell, type ReviewerTab } from "@/components/review/ReviewerShell";
import { SavedReviews } from "@/components/review/SavedReviews";
import { useOpsReviewHistory, usePortalWorklist } from "@/lib/queries";

function ReviewHomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: ReviewerTab = tabParam === "queue" ? "queue" : "saved";
  const worklist = usePortalWorklist();
  const history = useOpsReviewHistory(50);

  const queueCount = useMemo(
    () => worklist.data?.applications.length ?? null,
    [worklist.data?.applications.length],
  );
  const savedCount = useMemo(() => history.data?.count ?? null, [history.data?.count]);

  const setTab = (next: ReviewerTab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "saved") {
      params.delete("tab");
    } else {
      params.set("tab", "queue");
    }
    const query = params.toString();
    router.replace(query ? `/review?${query}` : "/review");
  };

  return (
    <ReviewerShell tab={tab} onTabChange={setTab} queueCount={queueCount} savedCount={savedCount}>
      {tab === "queue" ? (
        <ReviewQueue
          onOpen={(applicationId) => router.push(`/review/applications/${applicationId}`)}
        />
      ) : (
        <SavedReviews />
      )}
    </ReviewerShell>
  );
}

export default function ReviewHomePage() {
  return (
    <Suspense
      fallback={
        <ReviewerShell>
          <div className="reviewer-empty" role="status">
            <p className="reviewer-empty__title">Loading reviewer home</p>
            <p className="reviewer-empty__body">Preparing queue and saved reviews.</p>
          </div>
        </ReviewerShell>
      }
    >
      <ReviewHomeContent />
    </Suspense>
  );
}
