import { frontendConfig, pageTitles } from "./config.js";
import { renderNavbar } from "./components/navbar.js";
import { renderSidebar } from "./components/sidebar.js";
import { getCurrentPageKey, navigateTo } from "./router.js";
import { apiService } from "./services/api.js";
import { emptyState } from "./components/loading.js";
import { formatDateTime, formatStatusLabel, truncateText, escapeHtml } from "./utils/formatter.js";
import { showError } from "./utils/notifications.js";

let globalErrorHandlersBound = false;

export function bootPage({ pageKey, title, subtitle }) {
  renderSidebar();
  renderNavbar({
    title,
    subtitle,
    rightMeta: `<span class="topbar-badge">${escapeHtml(frontendConfig.appName)}</span>`,
  });
  document.title = `${title} | SPARX`;
  document.body.dataset.page = pageKey;
  bindGlobalErrorHandlers();
}

function bindGlobalErrorHandlers() {
  if (globalErrorHandlersBound) {
    return;
  }

  window.addEventListener("unhandledrejection", (event) => {
    const message = event.reason instanceof Error ? event.reason.message : "Unexpected request failure.";
    showError(message);
  });

  window.addEventListener("error", (event) => {
    const message = event.error instanceof Error ? event.error.message : "Unexpected browser error.";
    showError(message);
  });

  globalErrorHandlersBound = true;
}

async function loadHomeOverview() {
  const healthTarget = document.getElementById("home-health");
  const modulesTarget = document.getElementById("home-modules");
  const callsTarget = document.getElementById("home-recent-calls");

  if (!healthTarget || !modulesTarget || !callsTarget) {
    return;
  }

  try {
    const [health, summaries, campaigns, callbacks] = await Promise.all([
      apiService.get("/health"),
      apiService.get("/summaries"),
      apiService.get("/campaigns"),
      apiService.get("/callbacks"),
    ]);

    healthTarget.innerHTML = `
      <div class="detail-list">
        <div class="detail-row"><span class="detail-label">Backend</span><span>${escapeHtml(health.backend)}</span></div>
        <div class="detail-row"><span class="detail-label">Firebase</span><span>${escapeHtml(health.firebase)}</span></div>
        <div class="detail-row"><span class="detail-label">Twilio</span><span>${escapeHtml(health.twilio)}</span></div>
        <div class="detail-row"><span class="detail-label">Deepgram</span><span>${escapeHtml(health.deepgram)}</span></div>
        <div class="detail-row"><span class="detail-label">Gemma</span><span>${escapeHtml(health.details?.gemma?.status || "unknown")}</span></div>
      </div>
    `;

    modulesTarget.innerHTML = `
      <div class="widget-list">
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Campaigns</span><span class="status-pill running">${campaigns.length}</span></div>
          <div class="detail-text">Bulk calling, queue control, and CSV ingestion are available.</div>
        </div>
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Callbacks</span><span class="status-pill scheduled">${callbacks.length}</span></div>
          <div class="detail-text">Time-aware callback scheduling and retry orchestration are available.</div>
        </div>
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Summaries</span><span class="status-pill completed">${summaries.filter((item) => item.processed_by_ai).length}</span></div>
          <div class="detail-text">Gemma post-call intelligence is ready for processed calls.</div>
        </div>
      </div>
    `;

    const recentSummaries = summaries.slice(0, 4);
    if (!recentSummaries.length) {
      callsTarget.innerHTML = emptyState("No processed calls are available yet.");
      return;
    }

    callsTarget.innerHTML = `
      <div class="widget-list">
        ${recentSummaries
          .map(
            (item) => `
              <div class="widget-item">
                <div class="widget-item-header">
                  <span class="widget-item-title">${escapeHtml(item.lead_name)}</span>
                  <span class="status-pill ${escapeHtml(item.call_outcome || item.ai_processing_status)}">${escapeHtml(formatStatusLabel(item.call_outcome || item.ai_processing_status))}</span>
                </div>
                <div class="detail-text">${escapeHtml(truncateText(item.summary || item.next_action || "AI processing pending.", 120))}</div>
                <div class="detail-text">${escapeHtml(formatDateTime(item.call_date))}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load home overview.";
    healthTarget.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
    modulesTarget.innerHTML = emptyState("System data could not be loaded.");
    callsTarget.innerHTML = emptyState("Recent activity is unavailable.");
  }
}

function bindHomeActions() {
  document.querySelectorAll("[data-home-nav]").forEach((button) => {
    button.addEventListener("click", () => {
      const pageKey = button instanceof HTMLElement ? button.dataset.homeNav : null;
      if (pageKey) {
        navigateTo(pageKey);
      }
    });
  });
}

function initialiseHomePage() {
  const currentPageKey = getCurrentPageKey();
  if (currentPageKey !== "home") {
    return;
  }

  bootPage({
    pageKey: "home",
    title: pageTitles.home,
    subtitle: "Operate manual calls, campaigns, callbacks, and AI summaries from one place.",
  });
  bindHomeActions();
  loadHomeOverview();
}

initialiseHomePage();
