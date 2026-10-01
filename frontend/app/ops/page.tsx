"use client";

import { useRouter } from "next/navigation";

import { ReviewQueue } from "@/components/review/ReviewQueue";
import { ReviewerShell } from "@/components/review/ReviewerShell";

export default function OpsWorklistPage() {
  const router = useRouter();
  return (
    <ReviewerShell
      kicker="Operations"
      title="Operations queue"
      lede="Same files as the reviewer queue, opened in the operations file view."
    >
      <ReviewQueue
        title="Waiting for review"
        note="Open a file to check findings in the operations workspace."
        onOpen={(applicationId) => router.push(`/ops/applications/${applicationId}`)}
      />
    </ReviewerShell>
  );
}
