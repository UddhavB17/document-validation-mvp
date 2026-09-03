"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getReviewQueueNeighbors, readReviewQueue, updateReviewQueuePosition, type ReviewQueueSnapshot } from "@/lib/reviewQueue";

export function CaseQueueNavigation({ applicationId }: { applicationId: number }) {
  const [queue, setQueue] = useState<ReviewQueueSnapshot | null>(null);

  useEffect(() => {
    const snapshot = readReviewQueue();
    setQueue(snapshot);
    if (snapshot?.caseIds.includes(applicationId)) {
      const currentPosition = snapshot.caseIds.indexOf(applicationId);
      if (snapshot.position !== currentPosition) setQueue(updateReviewQueuePosition(currentPosition));
    }
  }, [applicationId]);

  useEffect(() => {
    const refresh = () => setQueue(readReviewQueue());
    window.addEventListener("storage", refresh);
    window.addEventListener("dmef-review-queue-change", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("dmef-review-queue-change", refresh);
    };
  }, []);

  const neighbors = getReviewQueueNeighbors(queue, applicationId);
  const hasQueuePosition = neighbors.position !== null;
  const queueLength = queue?.caseIds.length ?? 0;

  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className="mr-1 hidden font-semibold text-[#5C6B7A] sm:inline">
        {hasQueuePosition ? `${neighbors.position! + 1} of ${queueLength}` : "Queue"}
      </span>
      {neighbors.previousId ? (
        <Link
          href={`/applications/${neighbors.previousId}`}
          aria-label="Previous application in review queue"
          className="rounded-lg border border-[#E1E5EB] bg-white px-2.5 py-1.5 font-bold text-[#2B4C7E] transition-colors hover:bg-[#EAF0F8]"
        >
          ← Previous
        </Link>
      ) : (
        <span className="rounded-lg border border-[#E1E5EB] bg-slate-50 px-2.5 py-1.5 font-bold text-slate-400" aria-disabled="true">
          ← Previous
        </span>
      )}
      {neighbors.nextId ? (
        <Link
          href={`/applications/${neighbors.nextId}`}
          aria-label="Next application in review queue"
          className="rounded-lg border border-[#E1E5EB] bg-white px-2.5 py-1.5 font-bold text-[#2B4C7E] transition-colors hover:bg-[#EAF0F8]"
        >
          Next →
        </Link>
      ) : (
        <span className="rounded-lg border border-[#E1E5EB] bg-slate-50 px-2.5 py-1.5 font-bold text-slate-400" aria-disabled="true">
          Next →
        </span>
      )}
    </div>
  );
}
