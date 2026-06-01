import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { confirmDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { scheduledCallService } from "./services/scheduledCallService.js?v=operator-complete";
import { escapeHtml, formatStatusLabel } from "./utils/formatter.js";
import { showError, showSuccess } from "./utils/notifications.js";

const manualAiCallbackTableBody = document.getElementById("manual-ai-callback-table-body");
const manualExecutiveRequestTableBody = document.getElementById("manual-executive-request-table-body");
const campaignAiCallbackTableBody = document.getElementById("campaign-ai-callback-table-body");
const campaignExecutiveRequestTableBody = document.getElementById("campaign-executive-request-table-body");
const manualAiCallbackCount = document.getElementById("manual-ai-callback-count");
const manualExecutiveRequestCount = document.getElementById("manual-executive-request-count");
const campaignAiCallbackCount = document.getElementById("campaign-ai-callback-count");
const campaignExecutiveRequestCount = document.getElementById("campaign-executive-request-count");
const CLOSABLE_STATUSES = ["scheduled", "queued", "in_progress", "rescheduled", "failed"];
let isScheduledCallsRefreshing = false;

function formatScheduledDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Not available";
  }
  return date.toLocaleDateString();
}

function formatScheduledTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Not available";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function isCampaignSchedule(item) {
  return item.call_type === "campaign" || Boolean(item.campaign_id);
}

function renderAiCallbacks(items, tableBody, countElement, emptyMessage) {
  countElement.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(tableBody, 6, emptyMessage);
    return;
  }

  tableBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.name)}</td>
          <td>${escapeHtml(item.phone)}</td>
          <td>${escapeHtml(formatScheduledDate(item.scheduled_time))}</td>
          <td>${escapeHtml(formatScheduledTime(item.scheduled_time))}</td>
          <td><span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(formatStatusLabel(item.status))}</span></td>
          <td>${renderActions(item)}</td>
        </tr>
      `,
    )
    .join("");
}

function renderExecutiveRequests(items, tableBody, countElement, emptyMessage) {
  countElement.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(tableBody, 11, emptyMessage);
    return;
  }

  tableBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.name)}</td>
          <td>${escapeHtml(item.phone)}</td>
          <td>${escapeHtml(formatScheduledDate(item.scheduled_time))}</td>
          <td>${escapeHtml(formatScheduledTime(item.scheduled_time))}</td>
          <td><span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(formatStatusLabel(item.status))}</span></td>
          <td>${escapeHtml(formatCommunicationMode(item.communication_mode))}</td>
          <td>${escapeHtml(item.attendee_email || "-")}</td>
          <td>${renderMeetLink(item)}</td>
          <td>${escapeHtml(formatInviteStatus(item.invite_email_status))}</td>
          <td>${escapeHtml(item.assigned_executive || "Unassigned")}</td>
          <td>${renderActions(item)}</td>
        </tr>
      `,
    )
    .join("");
}

function renderActions(item) {
  if (!CLOSABLE_STATUSES.includes(item.status)) {
    return "-";
  }

  return `
    <button
      class="button ghost small"
      type="button"
      data-action="complete"
      data-scheduled-call-id="${escapeHtml(item.scheduled_call_id)}"
      data-scheduled-call-type="${escapeHtml(item.type)}"
    >
      Mark Completed
    </button>
  `;
}

async function loadScheduledCalls({ showLoading = true } = {}) {
  if (isScheduledCallsRefreshing) {
    return;
  }
  isScheduledCallsRefreshing = true;

  if (showLoading) {
    renderTableLoading(manualAiCallbackTableBody, 6, "Loading manual AI callbacks...");
    renderTableLoading(manualExecutiveRequestTableBody, 11, "Loading manual executive requests...");
    renderTableLoading(campaignAiCallbackTableBody, 6, "Loading campaign AI callbacks...");
    renderTableLoading(campaignExecutiveRequestTableBody, 11, "Loading campaign executive requests...");
  }

  try {
    const scheduledCalls = await scheduledCallService.listScheduledCalls();
    const manualAiCallbacks = scheduledCalls.filter((item) => item.type === "ai_callback" && !isCampaignSchedule(item));
    const manualExecutiveRequests = scheduledCalls.filter((item) => item.type === "executive_callback" && !isCampaignSchedule(item));
    const campaignAiCallbacks = scheduledCalls.filter((item) => item.type === "ai_callback" && isCampaignSchedule(item));
    const campaignExecutiveRequests = scheduledCalls.filter((item) => item.type === "executive_callback" && isCampaignSchedule(item));
    renderAiCallbacks(
      manualAiCallbacks,
      manualAiCallbackTableBody,
      manualAiCallbackCount,
      "No manual AI callbacks have been scheduled by the action yet.",
    );
    renderExecutiveRequests(
      manualExecutiveRequests,
      manualExecutiveRequestTableBody,
      manualExecutiveRequestCount,
      "No manual executive call requests have been scheduled by the action yet.",
    );
    renderAiCallbacks(
      campaignAiCallbacks,
      campaignAiCallbackTableBody,
      campaignAiCallbackCount,
      "No campaign AI callbacks have been scheduled by the action yet.",
    );
    renderExecutiveRequests(
      campaignExecutiveRequests,
      campaignExecutiveRequestTableBody,
      campaignExecutiveRequestCount,
      "No campaign executive call requests have been scheduled by the action yet.",
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load scheduled calls.";
    if (showLoading) {
      renderTableError(manualAiCallbackTableBody, 6, message);
      renderTableError(manualExecutiveRequestTableBody, 11, message);
      renderTableError(campaignAiCallbackTableBody, 6, message);
      renderTableError(campaignExecutiveRequestTableBody, 11, message);
    }
    showError(message);
  } finally {
    isScheduledCallsRefreshing = false;
  }
}

function formatCommunicationMode(value) {
  if (value === "google_meet") {
    return "Google Meet";
  }
  return "Phone Call";
}

function formatInviteStatus(value) {
  if (!value || value === "not_required") {
    return "-";
  }
  return formatStatusLabel(value);
}

function renderMeetLink(item) {
  if (!item.google_meet_link) {
    return "-";
  }
  return `<a href="${escapeHtml(item.google_meet_link)}" target="_blank" rel="noopener noreferrer">Open Meet</a>`;
}

async function handleScheduledCallAction(event) {
  const button = event.target.closest("[data-action='complete']");
  if (!button) {
    return;
  }

  const scheduledCallId = button.dataset.scheduledCallId;
  const scheduledCallType = button.dataset.scheduledCallType;
  if (!scheduledCallId) {
    return;
  }

  const label = scheduledCallType === "ai_callback" ? "AI callback" : "executive call request";
  const confirmed = await confirmDialog({
    title: "Mark scheduled call completed",
    message: `Mark this ${label} as completed? AI callbacks will be removed from the automatic callback queue.`,
    confirmLabel: "Mark completed",
  });
  if (!confirmed) {
    return;
  }

  try {
    button.disabled = true;
    await scheduledCallService.updateScheduledCallStatus(scheduledCallId, {
      status: "completed",
      notes: "Manually marked completed by operator.",
    });
    showSuccess("Scheduled call marked completed.");
    await loadScheduledCalls({ showLoading: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to mark scheduled call completed.";
    showError(message);
  } finally {
    button.disabled = false;
  }
}

bootPage({
  pageKey: "scheduled-calls",
  title: pageTitles["scheduled-calls"],
  subtitle: "Action-created AI callbacks and executive call requests.",
});

loadScheduledCalls({ showLoading: true });
manualAiCallbackTableBody.addEventListener("click", handleScheduledCallAction);
manualExecutiveRequestTableBody.addEventListener("click", handleScheduledCallAction);
campaignAiCallbackTableBody.addEventListener("click", handleScheduledCallAction);
campaignExecutiveRequestTableBody.addEventListener("click", handleScheduledCallAction);
window.setInterval(() => loadScheduledCalls({ showLoading: false }), frontendConfig.refreshIntervals.scheduledCallsMs);
