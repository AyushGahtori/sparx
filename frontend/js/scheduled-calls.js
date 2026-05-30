import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { confirmDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { scheduledCallService } from "./services/scheduledCallService.js";
import { escapeHtml, formatStatusLabel } from "./utils/formatter.js";
import { showError, showSuccess } from "./utils/notifications.js";

const aiCallbackTableBody = document.getElementById("ai-callback-table-body");
const executiveRequestTableBody = document.getElementById("executive-request-table-body");
const aiCallbackCount = document.getElementById("ai-callback-count");
const executiveRequestCount = document.getElementById("executive-request-count");
const CLOSABLE_STATUSES = ["scheduled", "queued", "in_progress", "rescheduled", "failed"];

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

function renderAiCallbacks(items) {
  aiCallbackCount.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(aiCallbackTableBody, 6, "No AI callbacks have been scheduled by the action yet.");
    return;
  }

  aiCallbackTableBody.innerHTML = items
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

function renderExecutiveRequests(items) {
  executiveRequestCount.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(executiveRequestTableBody, 7, "No executive call requests have been scheduled by the action yet.");
    return;
  }

  executiveRequestTableBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.name)}</td>
          <td>${escapeHtml(item.phone)}</td>
          <td>${escapeHtml(formatScheduledDate(item.scheduled_time))}</td>
          <td>${escapeHtml(formatScheduledTime(item.scheduled_time))}</td>
          <td><span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(formatStatusLabel(item.status))}</span></td>
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

async function loadScheduledCalls() {
  renderTableLoading(aiCallbackTableBody, 6, "Loading AI callbacks...");
  renderTableLoading(executiveRequestTableBody, 7, "Loading executive requests...");

  try {
    const scheduledCalls = await scheduledCallService.listScheduledCalls();
    const aiCallbacks = scheduledCalls.filter((item) => item.type === "ai_callback");
    const executiveRequests = scheduledCalls.filter((item) => item.type === "executive_callback");
    renderAiCallbacks(aiCallbacks);
    renderExecutiveRequests(executiveRequests);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load scheduled calls.";
    renderTableError(aiCallbackTableBody, 6, message);
    renderTableError(executiveRequestTableBody, 7, message);
    showError(message);
  }
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
    await loadScheduledCalls();
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

loadScheduledCalls();
aiCallbackTableBody.addEventListener("click", handleScheduledCallAction);
executiveRequestTableBody.addEventListener("click", handleScheduledCallAction);
window.setInterval(loadScheduledCalls, frontendConfig.refreshIntervals.scheduledCallsMs);
