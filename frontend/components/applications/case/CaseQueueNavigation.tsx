"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const QUEUE_STORAGE_KEYS = [
  "dmef_review_queue",
  "review_queue",
  "worklist_queue",
  "worklist_queue_ids",
  "review_queue_ids",
] as const;

type QueueEntry = number | string | { id?: number | string; application_id?: number | string };

export function CaseQueueNavigation({ applicationId }: { applicationId: number }) {
  const [queue, setQueue] = useState<number[]>([]);

  useEffect(() => {
    setQueue(readQueueFromSessionStorage());
  }, []);

  const currentIndex = queue.indexOf(applicationId);
  const previousId = currentIndex > 0 ? queue[currentIndex - 1] : null;
  const nextId = currentIndex >= 0 && currentIndex < queue.length - 1 ? queue[currentIndex + 1] : null;
  const hasQueuePosition = currentIndex >= 0;

  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className="mr-1 hidden font-semibold text-[#5C6B7A] sm:inline">
        {hasQueuePosition ? `${currentIndex + 1} of ${queue.length}` : "Queue"}
      </span>
      {previousId ? (
        <Link
          href={`/applications/${previousId}`}
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
      {nextId ? (
        <Link
          href={`/applications/${nextId}`}
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

function readQueueFromSessionStorage(): number[] {
  if (typeof window === "undefined") {
    return [];
  }

  for (const key of QUEUE_STORAGE_KEYS) {
    try {
      const rawValue = window.sessionStorage.getItem(key);
      if (!rawValue) {
        continue;
      }
      const parsed = parseQueueValue(rawValue);
      if (parsed.length > 0) {
        return parsed;
      }
    } catch {
      // Session storage can be unavailable in privacy-restricted contexts.
    }
  }
  return [];
}

function parseQueueValue(rawValue: string): number[] {
  let value: unknown = rawValue;
  try {
    value = JSON.parse(rawValue) as unknown;
  } catch {
    value = rawValue.split(",").map((item) => item.trim());
  }

  if (!Array.isArray(value) && typeof value === "object" && value !== null) {
    const candidate = value as { ids?: unknown; application_ids?: unknown; queue?: unknown; items?: unknown };
    value = candidate.ids ?? candidate.application_ids ?? candidate.queue ?? candidate.items ?? [];
  }

  if (!Array.isArray(value)) {
    return [];
  }

  const ids = value.map((entry: QueueEntry) => {
    if (typeof entry === "object" && entry !== null) {
      return Number(entry.id ?? entry.application_id);
    }
    return Number(entry);
  });
  return Array.from(new Set(ids.filter((id) => Number.isInteger(id) && id > 0)));
}
