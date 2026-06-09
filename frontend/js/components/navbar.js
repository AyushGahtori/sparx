import { frontendConfig } from "../config.js";
import { escapeHtml } from "../utils/formatter.js";

export function renderNavbar({ title, subtitle = "", rightMeta = "" }) {
  const root = document.getElementById("navbar-root");
  if (!root) {
    return;
  }

  const docsLinkMarkup = frontendConfig.docsUrl
    ? `<a class="topbar-badge" href="${escapeHtml(frontendConfig.docsUrl)}" target="_blank" rel="noreferrer">API Docs</a>`
    : "";

  root.innerHTML = `
    <div class="topbar">
      <div class="topbar-inner">
        <div class="topbar-copy">
          <h1 class="topbar-title">${escapeHtml(title)}</h1>
          <p class="topbar-subtitle">${escapeHtml(subtitle)}</p>
        </div>
        <button id="command-search-button" class="topbar-search" type="button" aria-label="Open command palette">
          <span>Search pages, actions, and workflows</span>
          <kbd class="topbar-kbd">Ctrl K</kbd>
        </button>
        <div class="topbar-meta">
          <span class="topbar-badge"><span class="system-dot" aria-hidden="true"></span>System Online</span>
          <span class="topbar-badge optional">${escapeHtml(frontendConfig.environmentLabel)}</span>
          ${docsLinkMarkup}
          ${rightMeta || ""}
          <button id="theme-toggle-button" class="topbar-icon-button" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">T</button>
          <button class="topbar-icon-button" type="button" aria-label="Notifications" title="Notifications">N</button>
          <span id="auth-status-slot"></span>
        </div>
      </div>
    </div>
  `;
}
