"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { useHealth, useApplicationReview } from "@/lib/queries";
import { FieldComparison } from "@/lib/api";

const navItems = [
  {
    href: "/upload",
    label: "Upload",
    icon: (
      <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
      </svg>
    )
  },
  {
    href: "/worklist",
    label: "Worklist",
    icon: (
      <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z" />
      </svg>
    )
  },
  {
    href: "/activity",
    label: "My Activity",
    icon: (
      <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    )
  },
  {
    href: "/settings",
    label: "Settings",
    icon: (
      <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.43l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.99l1.005.831a1.125 1.125 0 01.26 1.43l-1.297 2.247a1.125 1.125 0 01-1.37.491l-1.216-.456c-.356-.133-.751-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.37-.49l-1.296-2.247a1.125 1.125 0 01.26-1.43l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.831a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.645-.869l.214-1.28z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const health = useHealth();
  const [isSidebarHidden, setIsSidebarHidden] = useState(false);

  const appDetailMatch = pathname.match(/^\/applications\/(\d+)/);
  const appId = appDetailMatch ? Number(appDetailMatch[1]) : null;

  return (
    <div className="flex min-h-screen bg-[#F6F7FA] text-[#16202E]">
      <aside className={`shrink-0 border-r border-[#E1E5EB] bg-white sticky top-0 h-screen overflow-y-auto transition-all duration-300 flex flex-col justify-between ${
        isSidebarHidden ? "w-0 border-none overflow-hidden" : "w-64"
      }`}>
        <div>
          {/* Header Identity Branding */}
          <div className="border-b border-[#E1E5EB] px-5 py-4">
            <div className="text-xl font-bold font-serif text-[#16202E]">DMEF</div>
            <div className="text-[10px] font-extrabold text-[#5C6B7A] uppercase tracking-wider mt-0.5">MS Fincap Audit Portal</div>
          </div>
          
          {/* Nav list */}
          <nav className="space-y-1.5 px-3 py-4">
            {navItems.map((item) => {
              const active = pathname.startsWith(item.href);
              const isWorklist = item.label === "Worklist";
              const showSubmenu = isWorklist && appId !== null;

              return (
                <div key={item.href} className="space-y-1">
                  <Link
                    href={item.href}
                    className={`flex items-center gap-2.5 w-full text-left px-3.5 py-2.5 rounded-lg text-[13.5px] transition-all font-semibold ${
                      active && !showSubmenu
                        ? "bg-[#EAF0F8] text-[#2B4C7E]"
                        : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
                    }`}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </Link>

                  {showSubmenu && (
                    <Suspense fallback={<div className="pl-7 text-xs text-slate-400 italic">Loading tabs...</div>}>
                      <AppSidebarSubmenu appId={appId} />
                    </Suspense>
                  )}
                </div>
              );
            })}
          </nav>
        </div>

        {/* Footer Metrics & Shutdown */}
        <div className="space-y-4">
          <div className="mx-5 border-t border-[#E1E5EB] pt-4 text-xs font-semibold">
            <div className="mb-2 font-bold text-[#5C6B7A] uppercase tracking-wider text-[10px]">API Endpoint</div>
            <code className="block rounded bg-[#F6F7FA] border border-[#E1E5EB] px-2 py-1 text-[11px] font-mono text-[#16202E] font-medium truncate">
              127.0.0.1:8000
            </code>
          </div>

          <div className="mx-5 border-t border-[#E1E5EB] pt-4 text-xs font-semibold">
            <div className="mb-2 font-bold text-[#5C6B7A] uppercase tracking-wider text-[10px]">Local health</div>
            {health.isLoading ? (
              <div className="text-[#5C6B7A] italic">Checking...</div>
            ) : health.isError ? (
              <span className="stamp mismatch">API OFFLINE</span>
            ) : health.data ? (
              <span className={`stamp ${health.data.status === "ok" ? "match" : "mismatch"}`}>
                {health.data.status.toUpperCase()}
              </span>
            ) : (
              <span className="stamp mismatch">API OFFLINE</span>
            )}
          </div>

          {!health.isError && health.data && (
            <div className="mx-5 border-t border-[#E1E5EB] py-4">
              <button
                type="button"
                onClick={async () => {
                  if (window.confirm("Are you sure you want to stop DMEF? This will shut down both the Backend and UI servers.")) {
                    try {
                      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
                      await fetch(`${baseUrl}/shutdown`, { method: "POST" });
                    } catch (e) {
                      // Ignored: request will drop since server is shutting down
                    }
                    window.alert("DMEF program has been stopped. You can now close this browser tab.");
                  }
                }}
                className="w-full rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-700 shadow-sm transition-all duration-150 hover:bg-red-100 hover:text-red-800 active:scale-[0.98] select-none text-center cursor-pointer block"
              >
                Stop DMEF
              </button>
            </div>
          )}
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex h-14 items-center border-b border-[#E1E5EB] bg-white px-6">
          <button
            type="button"
            onClick={() => setIsSidebarHidden(!isSidebarHidden)}
            className="rounded-lg border border-[#E1E5EB] bg-slate-50 p-2 text-slate-600 hover:bg-slate-100 hover:text-[#16202E] active:scale-95 transition-all select-none cursor-pointer"
            title={isSidebarHidden ? "Reveal Navigation Sidebar" : "Hide Navigation Sidebar"}
          >
            {isSidebarHidden ? (
              <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" />
              </svg>
            ) : (
              <svg style={{ width: "18px", height: "18px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
              </svg>
            )}
          </button>
          <div className="ml-4 text-[10px] font-bold text-[#5C6B7A] uppercase tracking-widest">
            Document Validation Dashboard
          </div>
        </header>
        <main className="min-w-0 flex-1 px-8 py-6">{children}</main>
      </div>
    </div>
  );
}

function AppSidebarSubmenu({ appId }: { appId: number }) {
  const searchParams = useSearchParams();
  const activeTab = searchParams.get("tab") || "overview";
  const review = useApplicationReview(appId);

  const coreParams = review.data?.comparison_matrix?.core_parameters ?? [];
  const applicantList = review.data?.comparison_matrix?.applicants ?? [];
  const allFields: FieldComparison[] = [...coreParams, ...applicantList.flatMap((applicant) => applicant.fields)];
  const anomCount = allFields.filter((field) => field.status === "mismatch" || field.status === "attention").length;

  return (
    <div className="pl-6 pr-2 py-1 space-y-1 border-l border-slate-100 ml-5 mt-1 animate-fade-in flex flex-col">
      {[
        {
          key: "overview",
          label: "Overview",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
            </svg>
          )
        },
        {
          key: "extracted",
          label: "Extracted Data",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25A2.25 2.25 0 0113.5 8.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
          )
        },
        {
          key: "anomalies",
          label: "Anomalies & Flags",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.75c0 5.592 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.57-.598-3.75h-.152c-3.196 0-6.1-1.249-8.25-3.286zm0 13.036h.008v.008H12v-.008z" />
            </svg>
          ),
          badge: true
        },
        {
          key: "checklist",
          label: "Checklist & Decisions",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z" />
            </svg>
          )
        },
        {
          key: "logs",
          label: "Processing Logs",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          )
        },
        {
          key: "downloads",
          label: "Downloads",
          icon: (
            <svg style={{ width: "16px", height: "16px" }} className="shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          )
        }
      ].map((sub) => {
        const subActive = activeTab === sub.key;
        return (
          <Link
            key={sub.key}
            href={`/applications/${appId}?tab=${sub.key}`}
            className={`flex items-center justify-between w-full text-left px-2.5 py-1.5 rounded text-[11.5px] font-semibold transition-all cursor-pointer ${
              subActive
                ? "bg-[#EAF0F8] text-[#2B4C7E]"
                : "text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E]"
            }`}
          >
            <div className="flex items-center gap-2">
              {sub.icon}
              <span>{sub.label}</span>
            </div>
            {sub.badge && anomCount > 0 && (
              <span className={`font-mono text-[9px] px-1 py-0.5 rounded ${
                subActive ? "bg-[#2B4C7E] text-white" : "bg-[#FBEBE8] text-[#AF3B2E]"
              }`}>
                {anomCount}
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
