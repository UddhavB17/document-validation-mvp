import type { t } from "./i18n";

export type IconName = "worklist" | "intake" | "activity" | "settings" | "users" | "menu" | "close" | "collapse" | "expand" | "api" | "ops" | "signout";

export interface NavItem {
  href: string;
  labelKey: Parameters<typeof t>[1];
  fallback: string;
  icon: IconName;
  id: string;
  activePrefixes?: readonly string[];
}

export const OPERATIONS_NAV: readonly NavItem[] = [
  { href: "/ops", labelKey: "nav.worklist", fallback: "Worklist", icon: "worklist", id: "ops", activePrefixes: ["/ops/applications/"] },
  { href: "/ops/activity", labelKey: "nav.activity", fallback: "My activity", icon: "activity", id: "ops-activity" },
  { href: "/ops/settings", labelKey: "nav.preferences", fallback: "Preferences", icon: "settings", id: "ops-settings" },
];

export const ADMIN_NAV: readonly NavItem[] = [
  { href: "/admin/worklist", labelKey: "nav.worklist", fallback: "Worklist", icon: "worklist", id: "worklist", activePrefixes: ["/admin/applications/"] },
  { href: "/admin/upload", labelKey: "nav.intake", fallback: "Intake", icon: "intake", id: "intake" },
  { href: "/admin/activity", labelKey: "nav.activity", fallback: "My Activity", icon: "activity", id: "activity" },
];

export const ADMIN_UTILITY_NAV: readonly NavItem[] = [
  { href: "/admin/settings", labelKey: "nav.settings", fallback: "Settings", icon: "settings", id: "settings" },
  { href: "/admin/users", labelKey: "nav.users", fallback: "Users", icon: "users", id: "users" },
  { href: "/admin/llm", labelKey: "nav.llm", fallback: "LLM", icon: "api", id: "llm" },
];

export function getApplicationIdFromPath(pathname: string): number | null {
  const match = pathname.match(/^\/(?:admin\/applications|ops\/applications|applications)\/(\d+)/);
  return match ? Number(match[1]) : null;
}

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  return pathname === item.href
    || pathname.startsWith(`${item.href}/`)
    || Boolean(item.activePrefixes?.some((prefix) => pathname.startsWith(prefix)));
}

interface HeaderTitleRule {
  matches: (pathname: string) => boolean;
  title: (applicationId: number | null) => string;
}

const HEADER_TITLE_RULES: readonly HeaderTitleRule[] = [
  {
    matches: (pathname) => pathname.startsWith("/ops/applications/"),
    title: (applicationId) => `Case review · APP-${String(applicationId ?? 0).padStart(4, "0")}`,
  },
  { matches: (pathname) => pathname === "/ops/activity" || pathname.startsWith("/ops/activity/"), title: () => "My activity · Reviewer" },
  { matches: (pathname) => pathname === "/ops/settings" || pathname.startsWith("/ops/settings/"), title: () => "Preferences · Reviewer" },
  { matches: (pathname) => pathname === "/ops" || pathname.startsWith("/ops/"), title: () => "Document validation · Reviewer" },
];

export function resolveHeaderTitle(pathname: string, applicationId: number | null, isAdmin: boolean): string {
  const rule = HEADER_TITLE_RULES.find((candidate) => candidate.matches(pathname));
  if (rule) return rule.title(applicationId);
  if (isAdmin) return "Document validation · Admin";
  return "Document validation operations";
}
