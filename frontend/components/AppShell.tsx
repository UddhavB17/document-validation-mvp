"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { LanguageToggle } from "@/components/ops/LanguageToggle";
import { StatusBadge } from "@/components/StatusBadge";
import { useSession } from "@/lib/auth";
import { t, useLocale } from "@/lib/i18n";
import { sessionRedirectTarget, shouldRenderProtectedChildren } from "@/lib/sessionGate";
import { useApplicationReview, useHealth } from "@/lib/queries";
import { adminStartWorkerRequest } from "@/lib/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FieldComparison } from "@/lib/api";

type IconName = "worklist" | "intake" | "activity" | "settings" | "users" | "menu" | "close" | "collapse" | "expand" | "api" | "ops";

interface NavItem {
  href: string;
  labelKey: Parameters<typeof t>[1];
  fallback: string;
  icon: IconName;
  id: string;
}

const OPERATIONS_NAV: NavItem[] = [
  { href: "/ops", labelKey: "nav.worklist", fallback: "Worklist", icon: "worklist", id: "ops" },
];

const ADMIN_NAV: NavItem[] = [
  { href: "/admin/worklist", labelKey: "nav.worklist", fallback: "Worklist", icon: "worklist", id: "worklist" },
  { href: "/admin/upload", labelKey: "nav.intake", fallback: "Intake", icon: "intake", id: "intake" },
  { href: "/admin/activity", labelKey: "nav.activity", fallback: "My Activity", icon: "activity", id: "activity" },
];

const ADMIN_UTILITY_NAV: NavItem[] = [
  { href: "/admin/settings", labelKey: "nav.settings", fallback: "Settings", icon: "settings", id: "settings" },
  { href: "/admin/users", labelKey: "nav.users", fallback: "Users", icon: "users", id: "users" },
  { href: "/admin/llm", labelKey: "nav.llm", fallback: "LLM", icon: "api", id: "llm" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();

  // Backstop for sessions middleware did not reroute (soft navigation onto
  // an invalid session). Null while hydrating or on public paths, so this
  // can never bounce between targets.
  const redirectTarget = sessionRedirectTarget(session.status, pathname);
  useEffect(() => {
    if (redirectTarget !== null) {
      router.replace(redirectTarget);
    }
  }, [redirectTarget, router]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!shouldRenderProtectedChildren(session.status, pathname)) {
    // Hydration gate: mounting protected children (and their queries) while
    // the bearer is still loading sends unauthenticated requests whose 401s
    // would delete a valid session. Hold a placeholder instead.
    return (
      <div className="app-shell">
        <main id="main-content" className="app-shell__main" tabIndex={-1}>
          <p role="status">Loading…</p>
        </main>
      </div>
    );
  }

  return <ShellChrome pathname={pathname} role={session.role} onLogout={() => void session.logout()}>{children}</ShellChrome>;
}

function WorkerStartButton() {
  const queryClient = useQueryClient();
  const startWorker = useMutation({
    mutationFn: adminStartWorkerRequest,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });
  return (
    <div className="app-shell__worker-start">
      <button
        type="button"
        disabled={startWorker.isPending}
        onClick={() => void startWorker.mutate()}
        className="app-shell__nav-link"
        aria-label="Start worker"
      >
        <span className="app-shell__nav-text">
          {startWorker.isPending ? "Starting…" : "Start worker"}
        </span>
      </button>
      {startWorker.isError ? (
        <p className="app-shell__worker-error" role="alert">
          {startWorker.error.message}
        </p>
      ) : null}
      {startWorker.isSuccess ? (
        <p className="app-shell__worker-note" role="status">
          Worker starting — health refreshes automatically.
        </p>
      ) : null}
    </div>
  );
}

function ShellChrome({
  children,
  pathname,
  role,
  onLogout,
}: {
  children: React.ReactNode;
  pathname: string;
  role: string | null;
  onLogout: () => void;
}) {
  const { locale } = useLocale();
  const health = useHealth();
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const applicationId = getApplicationIdFromPath(pathname);
  const healthStatus = health.data?.status === "ok" ? "ok" : "failed";
  const isAdmin = role === "admin";
  const primaryNav = isAdmin ? ADMIN_NAV : OPERATIONS_NAV;
  const homeHref = isAdmin ? "/admin/worklist" : "/ops";

  const closeMobileNavigation = () => setIsMobileNavOpen(false);

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
            <Link href={homeHref} className="app-shell__brand" aria-label="DMEF operations review home" onClick={closeMobileNavigation}>
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
              {primaryNav.map((item) => {
                const active = isNavItemActive(item.id, item.href, pathname, applicationId);
                const showSubmenu = isAdmin && item.id === "worklist" && applicationId !== null;

                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`app-shell__nav-link${active ? " is-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      aria-label={item.fallback}
                      onClick={closeMobileNavigation}
                    >
                      <Icon name={item.icon} />
                      <span className="app-shell__nav-text">{t(locale, item.labelKey)}</span>
                    </Link>
                    {showSubmenu ? (
                      <Suspense fallback={null}>
                        <AppSidebarSubmenu applicationId={applicationId} />
                      </Suspense>
                    ) : null}
                  </li>
                );
              })}
              {isAdmin && applicationId !== null ? (
                <li>
                  <Link
                    href={`/ops/applications/${applicationId}`}
                    className="app-shell__nav-link"
                    aria-label={t(locale, "nav.viewAsOperations")}
                    onClick={closeMobileNavigation}
                  >
                    <Icon name="ops" />
                    <span className="app-shell__nav-text">{t(locale, "nav.viewAsOperations")}</span>
                  </Link>
                </li>
              ) : null}
            </ul>
          </nav>
        </div>

        <div className="app-shell__sidebar-bottom">
          <nav className="app-shell__utility-nav" aria-label="Utilities">
            <div className="app-shell__nav-label">Utilities</div>
            {isAdmin ? ADMIN_UTILITY_NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`app-shell__nav-link${active ? " is-active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.fallback}
                  onClick={closeMobileNavigation}
                >
                  <Icon name={item.icon} />
                  <span className="app-shell__nav-text">{t(locale, item.labelKey)}</span>
                </Link>
              );
            }) : null}
            <div className="app-shell__nav-row">
              <LanguageToggle />
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="app-shell__nav-link app-shell__signout"
              aria-label={t(locale, "nav.signOut")}
            >
              <Icon name="close" />
              <span className="app-shell__nav-text">{t(locale, "nav.signOut")}</span>
            </button>
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
            {isAdmin && healthStatus === "failed" ? <WorkerStartButton /> : null}
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
    </div>
  );
}

function getApplicationIdFromPath(pathname: string): number | null {
  const applicationPathMatch = pathname.match(/^\/(?:admin\/applications|ops\/applications|applications)\/(\d+)/);
  return applicationPathMatch ? Number(applicationPathMatch[1]) : null;
}

function isNavItemActive(itemId: string, href: string, pathname: string, applicationId: number | null) {
  if (itemId === "worklist" && applicationId !== null && pathname.startsWith("/admin/applications/")) {
    return true;
  }
  if (itemId === "ops" && applicationId !== null && pathname.startsWith("/ops/applications/")) {
    return true;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function AppSidebarSubmenu({ applicationId }: { applicationId: number }) {
  const searchParams = useSearchParams();
  const activeTab = searchParams.get("tab") || "review";
  const applicationReview = useApplicationReview(applicationId);

  const coreParameters = applicationReview.data?.comparison_matrix?.core_parameters ?? [];
  const applicants = applicationReview.data?.comparison_matrix?.applicants ?? [];
  const comparisonFields: FieldComparison[] = [
    ...coreParameters,
    ...applicants.flatMap((applicant) => applicant.fields),
  ];
  const anomalyCount = comparisonFields.filter((field) => field.status === "mismatch" || field.status === "attention").length;

  const tabs: Array<{ key: string; label: string; icon: IconName; showCount?: boolean }> = [
    { key: "review", label: "Review", icon: "worklist" },
    { key: "extracted", label: "Extracted data", icon: "intake" },
    { key: "checklist", label: "Checklist", icon: "worklist" },
    { key: "processing", label: "Processing", icon: "activity" },
    { key: "files", label: "Files", icon: "intake" },
  ];

  return (
    <ul className="app-shell__submenu" aria-label="Application review sections">
      {tabs.map((tab) => {
        const active = activeTab === tab.key;
        return (
          <li key={tab.key}>
            <Link
              href={tab.key === "review" ? `/admin/applications/${applicationId}` : `/admin/applications/${applicationId}?tab=${tab.key}`}
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
    users: <><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" /><circle cx="17" cy="9" r="2.5" /><path d="M16 14.6c2.6.3 5 2.3 5 5.4" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    collapse: <><path d="m15 6-6 6 6 6" /><path d="m21 6-6 6 6 6" /></>,
    expand: <><path d="m9 6 6 6-6 6" /><path d="m3 6 6 6-6 6" /></>,
    api: <><path d="M7 5v14M17 5v14M5 7h4M15 17h4" /><path d="M9 9h6v6H9z" /></>,
    ops: <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.5 2.5 2.5 4.5-5.5" /></>,
  };

  return (
    <svg className="app-shell__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
