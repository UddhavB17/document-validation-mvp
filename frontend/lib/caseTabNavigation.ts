type TabClick = Pick<MouseEvent,
  "button" | "metaKey" | "ctrlKey" | "altKey" | "shiftKey" | "defaultPrevented" | "preventDefault"
>;

/** Switch sections of this case locally; preserve normal links/new-tab clicks. */
export function navigateCaseTab(event: TabClick, href: string): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
  const url = new URL(href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) return;
  event.preventDefault();
  window.history.pushState(null, "", url.pathname + url.search + url.hash);
}
