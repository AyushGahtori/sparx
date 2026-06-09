import { getCurrentPageKey, getSidebarItems, toPageHref } from "../router.js";
import { escapeHtml } from "../utils/formatter.js";

export function renderSidebar() {
  const root = document.getElementById("sidebar-root");
  if (!root) {
    return;
  }

  const currentPageKey = getCurrentPageKey();
  const iconMap = {
    dashboard: "D",
    "manual-call": "M",
    campaigns: "C",
    callbacks: "Q",
    "meeting-details": "N",
    "call-history": "H",
    summaries: "A",
    settings: "S",
  };
  const linksMarkup = getSidebarItems()
    .map((item) => {
      const isActive = item.key === currentPageKey;
      return `
        <a class="sidebar-link ${isActive ? "active" : ""}" href="${toPageHref(item.key)}" data-page-key="${item.key}" data-icon="${escapeHtml(iconMap[item.key] || item.label[0])}">
          <span>${escapeHtml(item.label)}</span>
        </a>
      `;
    })
    .join("");

  root.innerHTML = `
    <div class="sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-brand-row">
          <span class="sidebar-logo" aria-hidden="true">SX</span>
          <div>
            <a href="${toPageHref("home")}">SPARX</a>
            <span class="sidebar-caption">Control Center</span>
          </div>
        </div>
        <div class="sidebar-system-card">
          <strong>AI Sales Automation</strong>
          <span>Calls, campaigns, callbacks, and post-call intelligence.</span>
        </div>
      </div>
      <nav class="sidebar-nav" aria-label="Primary">
        ${linksMarkup}
      </nav>
      <div class="sidebar-footer">
        <span class="sidebar-footer-kbd">Ctrl K</span>
        <span>Command palette and global navigation</span>
      </div>
    </div>
  `;
}
