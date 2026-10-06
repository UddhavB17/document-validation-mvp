import Link from "next/link";

import type { CaseTab } from "@/components/applications/types";

const CASE_TABS: ReadonlyArray<{ key: CaseTab; label: string }> = [
  { key: "review", label: "Review" },
  { key: "extracted", label: "Extracted data" },
  { key: "checklist", label: "Checklist" },
  { key: "processing", label: "Processing" },
  { key: "files", label: "Files" },
];

function caseTabHref(applicationId: number, tab: CaseTab): string {
  return tab === "review" ? `/admin/applications/${applicationId}` : `/admin/applications/${applicationId}?tab=${tab}`;
}

export function CaseNavigation({ applicationId, activeTab }: { applicationId: number; activeTab: CaseTab }) {
  return (
    <nav
      aria-label="Application case sections"
      className="flex min-w-0 flex-wrap items-center gap-1 rounded-xl border border-[#E1E5EB] bg-white p-1.5 shadow-2xs"
    >
      {CASE_TABS.map((tab) => {
        const active = tab.key === activeTab;
        return (
          <Link
            key={tab.key}
            href={caseTabHref(applicationId, tab.key)}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-3.5 py-2 text-[13px] font-bold transition-colors sm:px-4 ${
              active
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
