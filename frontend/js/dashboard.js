import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { apiService } from "./services/api.js";
import { callbackService } from "./services/callbackService.js";
import { callService } from "./services/callService.js";
import { campaignService } from "./services/campaignService.js";
import { summaryService } from "./services/summaryService.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { emptyState, errorState } from "./components/loading.js";
import {
  escapeHtml,
  formatDateTime,
  formatStatusLabel,
  truncateText,
} from "./utils/formatter.js";
import { showError, showSuccess } from "./utils/notifications.js";

const kpiRoot = document.getElementById("dashboard-kpis");
const recentCallsBody = document.getElementById("recent-calls-body");
const campaignStatusWidget = document.getElementById("campaign-status-widget");
const callbackQueueWidget = document.getElementById("callback-queue-widget");
const refreshButton = document.getElementById("refresh-dashboard-button");

function buildKpiCards({ calls, callbacks, summaries }) {
  const campaignCalls = calls.filter((call) => call.call_type === "campaign").length;
  const manualCalls = calls.length - campaignCalls;
  const callbacksPending = callbacks.filter((callback) =>
    ["scheduled", "queued", "in_progress", "rescheduled", "failed"].includes(callback.status),
  ).length;
  const meetingsRequested = calls.filter(
    (call) => call.meeting_requested || call.call_outcome === "meeting_requested",
  ).length;
  const hotLeads = summaries.filter((summary) => summary.lead_type === "hot").length;

  const cards = [
    { label: "Total Calls", value: calls.length, footnote: "All stored call documents" },
    { label: "Campaign Calls", value: campaignCalls, footnote: "Bulk queue-driven outbound calls" },
    { label: "Manual Calls", value: manualCalls, footnote: "Individual and callback-origin calls" },
    { label: "Callbacks Pending", value: callbacksPending, footnote: "Open callback queue items" },
    { label: "Meetings Requested", value: meetingsRequested, footnote: "Calls flagged for meetings" },
    { label: "Hot Leads", value: hotLeads, footnote: "AI-classified hot opportunities" },
  ];

  kpiRoot.innerHTML = cards
    .map(
      (card) => `
        <div class="stat-card">
          <span class="stat-label">${escapeHtml(card.label)}</span>
          <span class="stat-value">${card.value}</span>
          <span class="stat-footnote">${escapeHtml(card.footnote)}</span>
        </div>
      `,
    )
    .join("");
}

function renderRecentCalls(calls) {
  if (!calls.length) {
    renderTableEmpty(recentCallsBody, 5, "No calls have been stored yet.");
    return;
  }

  recentCallsBody.innerHTML = calls
    .slice(0, 8)
    .map(
      (call) => `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(call.lead_name)}</strong>
              <span class="table-subtext">${escapeHtml(call.phone)}</span>
            </div>
          </td>
          <td><span class="status-pill ${escapeHtml(call.status)}">${escapeHtml(formatStatusLabel(call.status))}</span></td>
          <td>${escapeHtml(formatDateTime(call.ended_at || call.created_at))}</td>
          <td>${call.lead_type ? `<span class="status-pill ${escapeHtml(call.lead_type)}">${escapeHtml(call.lead_type)}</span>` : "-"}</td>
          <td>${call.call_outcome ? `<span class="status-pill ${escapeHtml(call.call_outcome)}">${escapeHtml(formatStatusLabel(call.call_outcome))}</span>` : "-"}</td>
        </tr>
      `,
    )
    .join("");
}

function renderCampaignWidget(campaigns) {
  if (!campaigns.length) {
    campaignStatusWidget.innerHTML = emptyState("No campaigns have been created yet.");
    return;
  }

  const statusRank = { running: 0, scheduled: 1, paused: 2, failed: 3, completed: 4, cancelled: 5 };
  const sortedCampaigns = [...campaigns].sort((left, right) => {
    const leftRank = statusRank[left.status] ?? 99;
    const rightRank = statusRank[right.status] ?? 99;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    return new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime();
  });

  campaignStatusWidget.innerHTML = `
    <div class="widget-list">
      ${sortedCampaigns
        .slice(0, 5)
        .map(
          (campaign) => `
            <div class="widget-item">
              <div class="widget-item-header">
                <span class="widget-item-title">${escapeHtml(campaign.campaign_name)}</span>
                <span class="status-pill ${escapeHtml(campaign.status)}">${escapeHtml(campaign.status)}</span>
              </div>
              <div class="detail-text">${campaign.completed_calls}/${campaign.total_contacts} completed | ${campaign.success_rate.toFixed(0)}% success</div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderCallbackWidget(callbacks) {
  if (!callbacks.length) {
    callbackQueueWidget.innerHTML = emptyState("No callbacks are waiting in the queue.");
    return;
  }

  const sortedCallbacks = [...callbacks].sort(
    (left, right) =>
      new Date(left.normalized_callback_time).getTime() - new Date(right.normalized_callback_time).getTime(),
  );

  callbackQueueWidget.innerHTML = `
    <div class="widget-list">
      ${sortedCallbacks
        .slice(0, 5)
        .map(
          (callback) => `
            <div class="widget-item">
              <div class="widget-item-header">
                <span class="widget-item-title">${escapeHtml(callback.lead_name)}</span>
                <span class="status-pill ${escapeHtml(callback.priority)}">${escapeHtml(callback.priority)}</span>
              </div>
              <div class="detail-text">${escapeHtml(formatDateTime(callback.normalized_callback_time))}</div>
              <div class="detail-text">${escapeHtml(truncateText(callback.callback_reason, 90))}</div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

let isDashboardRefreshing = false;

async function loadDashboard({ showLoading = true } = {}) {
  if (isDashboardRefreshing) {
    return;
  }
  isDashboardRefreshing = true;

  if (showLoading) {
    renderTableLoading(recentCallsBody, 5, "Loading recent calls...");
    campaignStatusWidget.innerHTML = "Loading campaigns...";
    callbackQueueWidget.innerHTML = "Loading callbacks...";
  }

  try {
    const [health, calls, campaigns, callbacks, summaries] = await Promise.all([
      apiService.get("/health"),
      callService.listCalls(),
      campaignService.listCampaigns(),
      callbackService.listCallbacks(),
      summaryService.listSummaries(),
    ]);

    buildKpiCards({ calls, callbacks, summaries });
    renderRecentCalls(calls);
    renderCampaignWidget(campaigns);
    renderCallbackWidget(callbacks);
    refreshButton.dataset.lastStatus = health.status;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load dashboard data.";
    if (showLoading) {
      renderTableError(recentCallsBody, 5, message);
      campaignStatusWidget.innerHTML = errorState(message);
      callbackQueueWidget.innerHTML = errorState(message);
    }
    showError(message);
  } finally {
    isDashboardRefreshing = false;
  }
}

bootPage({
  pageKey: "dashboard",
  title: pageTitles.dashboard,
  subtitle: "KPI cards, recent calls, campaign progress, and callback workload.",
});

refreshButton.addEventListener("click", async () => {
  await loadDashboard({ showLoading: true });
  showSuccess("Dashboard refreshed.");
});

loadDashboard({ showLoading: true });
window.setInterval(() => loadDashboard({ showLoading: false }), frontendConfig.refreshIntervals.dashboardMs);
