import { frontendConfig } from "../config.js";
import { escapeHtml } from "../utils/formatter.js";

export function renderNavbar({ title, subtitle = "", rightMeta = "" }) {
  const root = document.getElementById("navbar-root");
  if (!root) {
    return;
  }

  root.innerHTML = `
    <div class="topbar">
      <div class="topbar-inner">
        <div class="topbar-copy">
          <h1 class="topbar-title">${escapeHtml(title)}</h1>
          <p class="topbar-subtitle">${escapeHtml(subtitle)}</p>
        </div>
        <div class="topbar-meta">
          <span class="topbar-badge">${escapeHtml(frontendConfig.environmentLabel)}</span>
          <a class="topbar-badge" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API Docs</a>
          ${rightMeta || ""}
        </div>
      </div>
    </div>
  `;
}
