import { getCurrentPageKey, getSidebarItems, toPageHref } from "../router.js";
import { escapeHtml } from "../utils/formatter.js";

export function renderSidebar() {
  const root = document.getElementById("sidebar-root");
  if (!root) {
    return;
  }

  const currentPageKey = getCurrentPageKey();
  const linksMarkup = getSidebarItems()
    .map((item) => {
      const isActive = item.key === currentPageKey;
      return `
        <a class="sidebar-link ${isActive ? "active" : ""}" href="${toPageHref(item.key)}" data-page-key="${item.key}">
          <span>${escapeHtml(item.label)}</span>
        </a>
      `;
    })
    .join("");

  root.innerHTML = `
    <div class="sidebar">
      <div class="sidebar-brand">
        <a href="${toPageHref("home")}">SPARX</a>
        <span class="sidebar-caption">AI Agent Calling Module</span>
      </div>
      <nav class="sidebar-nav" aria-label="Primary">
        ${linksMarkup}
      </nav>
      <div class="sidebar-footer">
        Backend-integrated MVP dashboard
      </div>
    </div>
  `;
}
