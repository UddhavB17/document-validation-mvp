"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { useApplicationReview, useHealth } from "@/lib/queries";
import type { FieldComparison } from "@/lib/api";

type IconName = "worklist" | "intake" | "activity" | "settings" | "menu" | "close" | "collapse" | "expand" | "api" | "stop";

const primaryNavItems: Array<{ href: string; label: string; icon: IconName; id: string }> = [
  { href: "/worklist", label: "Worklist", icon: "worklist", id: "worklist" },
  { href: "/upload", label: "Intake", icon: "intake", id: "intake" },
  { href: "/activity", label: "My Activity", icon: "activity", id: "activity" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const health = useHealth();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [isStopDialogOpen, setIsStopDialogOpen] = useState(false);
  const [stopNotice, setStopNotice] = useState<string | null>(null);
  const applicationId = getApplicationIdFromPath(pathname);
  const healthStatus = health.data?.status === "ok" ? "ok" : "failed";

  const closeMobileNavigation = () => setIsMobileNavOpen(false);
  const handleStopDmef = async () => {
    setIsStopDialogOpen(false);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
      await fetch(`${baseUrl}/shutdown`, { method: "POST" });
      setStopNotice("Stop request sent. You can close this browser tab.");
    } catch {
      setStopNotice("The stop request could not reach the local API.");
    }
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>

      <aside
        id="primary-navigation"
        className="app-shell__sidebar"
        data-collapsed={isSidebarCollapsed}
        data-mobile-open={isMobileNavOpen}
        aria-label="DMEF navigation"
      >
        <div className="app-shell__sidebar-top">
          <div className="app-shell__brand-row">
            <Link href="/worklist" className="app-shell__brand" aria-label="DMEF operations review home" onClick={closeMobileNavigation}>
              <span className="app-shell__brand-mark" aria-hidden="true">D</span>
              <span className="app-shell__brand-copy">
                <span className="app-shell__brand-name">DMEF</span>
                <span className="app-shell__brand-subtitle">Operations review</span>
              </span>
            </Link>
            <button
              type="button"
              className="app-shell__mobile-close"
              aria-label="Close navigation menu"
              onClick={closeMobileNavigation}
            >
              <Icon name="close" />
            </button>
          </div>

          <nav className="app-shell__primary-nav" aria-label="Primary">
            <div className="app-shell__nav-label">Workspace</div>
            <ul className="app-shell__nav-list">
              {primaryNavItems.map((item) => {
                const active = isNavItemActive(item.id, item.href, pathname, applicationId);
                const showSubmenu = item.id === "worklist" && applicationId !== null;

                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`app-shell__nav-link${active ? " is-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      aria-label={item.label}
                      onClick={closeMobileNavigation}
                    >
                      <Icon name={item.icon} />
                      <span className="app-shell__nav-text">{item.label}</span>
                    </Link>
                    {showSubmenu ? (
                      <Suspense fallback={null}>
                        <AppSidebarSubmenu applicationId={applicationId} />
                      </Suspense>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>

        <div className="app-shell__sidebar-bottom">
          <nav className="app-shell__utility-nav" aria-label="Utilities">
            <div className="app-shell__nav-label">Utilities</div>
            <Link
              href="/settings"
              className={`app-shell__nav-link${pathname.startsWith("/settings") ? " is-active" : ""}`}
              aria-current={pathname.startsWith("/settings") ? "page" : undefined}
              aria-label="Settings"
              onClick={closeMobileNavigation}
            >
              <Icon name="settings" />
              <span className="app-shell__nav-text">Settings</span>
            </Link>
          </nav>

          <div className="app-shell__health" aria-label="API health">
            <div className="app-shell__health-heading">
              <span className="app-shell__nav-label">API health</span>
              <Icon name="api" />
            </div>
            {health.isLoading ? (
              <span className="app-shell__health-checking">Checking</span>
            ) : (
              <StatusBadge status={healthStatus} />
            )}
            <code className="app-shell__endpoint">127.0.0.1:8000</code>
          </div>

          <div className="app-shell__stop-area">
            {stopNotice ? <div className="app-shell__stop-notice" role="status">{stopNotice}</div> : null}
            <button
              type="button"
              className="app-shell__stop-button"
              onClick={() => setIsStopDialogOpen(true)}
              disabled={health.isLoading || health.isError || !health.data}
              aria-label="Stop DMEF"
            >
              <Icon name="stop" />
              <span className="app-shell__nav-text">Stop DMEF</span>
            </button>
          </div>
        </div>
      </aside>

      {isMobileNavOpen ? (
        <button type="button" className="app-shell__scrim" aria-label="Close navigation menu" onClick={closeMobileNavigation} />
      ) : null}

      <div className="app-shell__content">
        <header className="app-shell__header">
          <button
            type="button"
            className="app-shell__mobile-menu"
            aria-expanded={isMobileNavOpen}
            aria-controls="primary-navigation"
            aria-label={isMobileNavOpen ? "Close navigation menu" : "Open navigation menu"}
            onClick={() => setIsMobileNavOpen((open) => !open)}
          >
            <Icon name="menu" />
          </button>
          <button
            type="button"
            className="app-shell__collapse-toggle"
            aria-expanded={!isSidebarCollapsed}
            aria-controls="primary-navigation"
            aria-label={isSidebarCollapsed ? "Expand navigation sidebar" : "Collapse navigation sidebar"}
            onClick={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
          >
            <Icon name={isSidebarCollapsed ? "expand" : "collapse"} />
          </button>
          <div className="app-shell__header-copy">
            <span className="app-shell__header-kicker">DMEF</span>
            <span className="app-shell__header-title">Document validation operations</span>
          </div>
        </header>
        <main id="main-content" className="app-shell__main" tabIndex={-1}>{children}</main>
      </div>

      <ConfirmDialog
        open={isStopDialogOpen}
        title="Stop DMEF?"
        description="This will shut down the local backend and UI servers. Any work currently processing may be interrupted. Continue only if you are ready to stop the local workspace."
        confirmLabel="Stop DMEF"
        onConfirm={handleStopDmef}
        onCancel={() => setIsStopDialogOpen(false)}
      />
    </div>
  );
}

function getApplicationIdFromPath(pathname: string): number | null {
  const applicationPathMatch = pathname.match(/^\/applications\/(\d+)/);
  return applicationPathMatch ? Number(applicationPathMatch[1]) : null;
}

function isNavItemActive(itemId: string, href: string, pathname: string, applicationId: number | null) {
  if (itemId === "worklist" && applicationId !== null) {
    return true;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function AppSidebarSubmenu({ applicationId }: { applicationId: number }) {
  const searchParams = useSearchParams();
  const activeTab = searchParams.get("tab") || "overview";
  const applicationReview = useApplicationReview(applicationId);

  const coreParameters = applicationReview.data?.comparison_matrix?.core_parameters ?? [];
  const applicants = applicationReview.data?.comparison_matrix?.applicants ?? [];
  const comparisonFields: FieldComparison[] = [
    ...coreParameters,
    ...applicants.flatMap((applicant) => applicant.fields),
  ];
  const anomalyCount = comparisonFields.filter((field) => field.status === "mismatch" || field.status === "attention").length;

  const tabs: Array<{ key: string; label: string; icon: IconName; showCount?: boolean }> = [
    { key: "overview", label: "Overview", icon: "worklist" },
    { key: "extracted", label: "Extracted data", icon: "intake" },
    { key: "anomalies", label: "Anomalies & flags", icon: "stop", showCount: true },
    { key: "checklist", label: "Checklist & decisions", icon: "worklist" },
    { key: "logs", label: "Processing logs", icon: "activity" },
    { key: "downloads", label: "Downloads", icon: "intake" },
  ];

  return (
    <ul className="app-shell__submenu" aria-label="Application review sections">
      {tabs.map((tab) => {
        const active = activeTab === tab.key;
        return (
          <li key={tab.key}>
            <Link
              href={`/applications/${applicationId}?tab=${tab.key}`}
              className={`app-shell__submenu-link${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <Icon name={tab.icon} />
              <span>{tab.label}</span>
              {tab.showCount && anomalyCount > 0 ? <span className="app-shell__count">{anomalyCount}</span> : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    worklist: <><path d="m5 12 4 4L19 6" /><path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></>,
    intake: <><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M4 21h16" /></>,
    activity: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3 2" /></>,
    settings: <><path d="M12 3v2M12 19v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" /><circle cx="12" cy="12" r="3.5" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    collapse: <><path d="m15 6-6 6 6 6" /><path d="m21 6-6 6 6 6" /></>,
    expand: <><path d="m9 6 6 6-6 6" /><path d="m3 6 6 6-6 6" /></>,
    api: <><path d="M7 5v14M17 5v14M5 7h4M15 17h4" /><path d="M9 9h6v6H9z" /></>,
    stop: <><path d="M8 5h8l3 3v8l-3 3H8l-3-3V8l3-3Z" /><path d="M9 9h6v6H9z" /></>,
  };

  return (
    <svg className="app-shell__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
