const PAGE_MAP = Object.freeze({
  home: { key: "home", label: "Home", path: "index.html" },
  dashboard: { key: "dashboard", label: "Dashboard", path: "pages/dashboard.html" },
  "manual-call": { key: "manual-call", label: "Manual Call", path: "pages/manual-call.html" },
  campaigns: { key: "campaigns", label: "Campaigns", path: "pages/campaigns.html" },
  "scheduled-calls": { key: "scheduled-calls", label: "Scheduled Calls", path: "pages/scheduled-calls.html" },
  callbacks: { key: "callbacks", label: "Callbacks", path: "pages/callbacks.html" },
  "call-history": { key: "call-history", label: "Call History", path: "pages/call-history.html" },
  summaries: { key: "summaries", label: "Summaries", path: "pages/summaries.html" },
  settings: { key: "settings", label: "Diagnostics", path: "pages/settings.html" },
});

const SIDEBAR_ITEMS = Object.freeze([
  PAGE_MAP.dashboard,
  PAGE_MAP["manual-call"],
  PAGE_MAP.campaigns,
  PAGE_MAP["scheduled-calls"],
  PAGE_MAP.callbacks,
  PAGE_MAP["call-history"],
  PAGE_MAP.summaries,
  PAGE_MAP.settings,
]);

function isNestedPage() {
  return window.location.pathname.replace(/\\/g, "/").includes("/pages/");
}

function getBasePrefix() {
  return isNestedPage() ? "../" : "./";
}

export function getPageDefinition(pageKey) {
  return PAGE_MAP[pageKey] || PAGE_MAP.dashboard;
}

export function getSidebarItems() {
  return SIDEBAR_ITEMS;
}

export function getCurrentPageKey() {
  const path = window.location.pathname.replace(/\\/g, "/");

  if (
    path === "/" ||
    path === "" ||
    path.endsWith("/index.html") ||
    path.endsWith("/frontend/") ||
    path.endsWith("/frontend")
  ) {
    return "home";
  }

  for (const page of Object.values(PAGE_MAP)) {
    if (path.includes(page.path.replace("pages/", "/pages/"))) {
      return page.key;
    }
  }

  return "dashboard";
}

export function toPageHref(pageKey) {
  const page = getPageDefinition(pageKey);
  return `${getBasePrefix()}${page.path}`;
}

export function buildQueryString(params = {}) {
  const searchParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });

  return searchParams.toString();
}

export function navigateTo(pageKey, params = {}) {
  const href = toPageHref(pageKey);
  const query = buildQueryString(params);
  window.location.href = query ? `${href}?${query}` : href;
}

export function getSearchParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}
