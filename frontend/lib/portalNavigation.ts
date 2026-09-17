export type PortalView = "dashboard" | "report" | "reviewed" | "checklist";

export function portalViewFromSearch(searchParams: URLSearchParams): PortalView {
  if (searchParams.get("exception")) return "report";
  if (searchParams.get("tab") === "reviewed") return "reviewed";
  if (searchParams.get("tab") === "checklist") return "checklist";
  return "dashboard";
}

export function portalApplicationHref(
  applicationId: number,
  currentSearch: string,
  next: { view: PortalView; selectedKey?: string | null },
): string {
  const params = new URLSearchParams(currentSearch);
  params.delete("exception");
  if (next.view === "report" && next.selectedKey) {
    params.set("tab", "action-needed");
    params.set("exception", next.selectedKey);
  } else if (next.view === "reviewed") {
    params.set("tab", "reviewed");
  } else if (next.view === "checklist") {
    params.set("tab", "checklist");
  } else if (next.view === "dashboard") {
    params.delete("tab");
  }
  const query = params.toString();
  return `/ops/applications/${applicationId}${query ? `?${query}` : ""}`;
}
