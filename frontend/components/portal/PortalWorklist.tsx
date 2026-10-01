"use client";

import { ReviewQueue } from "@/components/review/ReviewQueue";
import { ReviewerShell } from "@/components/review/ReviewerShell";

export function PortalWorklist({
  onOpen,
  chrome = true,
}: {
  onOpen: (applicationId: number) => void;
  chrome?: boolean;
}) {
  const queue = (
    <ReviewQueue
      onOpen={onOpen}
      title="Your loan files"
      note="Open a file to see what needs attention."
    />
  );

  if (!chrome) {
    return queue;
  }

  return (
    <ReviewerShell
      kicker="My files"
      title="Your loan files"
      lede="Open a file to see what still needs attention, in the same calm layout as the rest of your workspace."
    >
      {queue}
    </ReviewerShell>
  );
}
