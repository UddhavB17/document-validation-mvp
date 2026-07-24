"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useHealth } from "@/lib/queries";
import { statusTone } from "@/lib/format";

const navItems = [
  { href: "/upload", label: "Upload" },
  { href: "/worklist", label: "Worklist" },
  { href: "/activity", label: "My Activity" },
  { href: "/settings", label: "Settings" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const health = useHealth();
  const [isSidebarHidden, setIsSidebarHidden] = useState(false);

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <aside className={`shrink-0 border-r border-slate-200 bg-white sticky top-0 h-screen overflow-y-auto transition-all duration-300 ${
        isSidebarHidden ? "w-0 border-none overflow-hidden" : "w-64"
      }`}>
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="text-xl font-semibold">DMEF</div>
          <div className="text-sm text-slate-500">Document Matching Early Finder</div>
        </div>
        <nav className="space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded px-3 py-2 text-sm font-medium ${active ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-100"
                  }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mx-5 border-t border-slate-200 py-4 text-sm">
          <div className="mb-2 font-medium text-slate-700">API</div>
          <code className="block rounded bg-slate-100 px-2 py-1 text-xs">127.0.0.1:8000</code>
        </div>
        <div className="mx-5 border-t border-slate-200 py-4 text-sm">
          <div className="mb-1 font-medium text-slate-700">Local health</div>
          {health.isLoading ? (
            <div className="text-slate-500">Checking...</div>
          ) : health.isError ? (
            <div className="text-red-700">API unavailable</div>
          ) : health.data ? (
            <div className={statusTone(health.data.status)}>{health.data.status.toUpperCase()}</div>
          ) : (
            <div className="text-red-700">API unavailable</div>
          )}
        </div>
        {!health.isError && health.data && (
          <div className="mx-5 border-t border-slate-200 py-3">
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
              className="w-full rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700 shadow-sm transition-all duration-150 hover:bg-red-100 hover:text-red-800 active:scale-[0.98] select-none text-center block"
            >
              Stop DMEF
            </button>
          </div>
        )}
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex h-14 items-center border-b border-slate-200 bg-white px-6">
          <button
            type="button"
            onClick={() => setIsSidebarHidden(!isSidebarHidden)}
            className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-800 active:scale-95 transition-all select-none"
            title={isSidebarHidden ? "Reveal Navigation Sidebar" : "Hide Navigation Sidebar"}
          >
            {isSidebarHidden ? (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
              </svg>
            )}
          </button>
          <div className="ml-4 text-xs font-bold text-slate-400 uppercase tracking-widest">
            Document Validation Dashboard
          </div>
        </header>
        <main className="min-w-0 flex-1 px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
