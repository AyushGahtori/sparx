import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { scheduledCallService } from "./services/scheduledCallService.js";
import { escapeHtml, formatStatusLabel } from "./utils/formatter.js";
import { showError } from "./utils/notifications.js";

const aiCallbackTableBody = document.getElementById("ai-callback-table-body");
const executiveRequestTableBody = document.getElementById("executive-request-table-body");
const aiCallbackCount = document.getElementById("ai-callback-count");
const executiveRequestCount = document.getElementById("executive-request-count");

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
    renderTableEmpty(aiCallbackTableBody, 5, "No AI callbacks have been scheduled by the action yet.");
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
        </tr>
      `,
    )
    .join("");
}

function renderExecutiveRequests(items) {
  executiveRequestCount.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(executiveRequestTableBody, 6, "No executive call requests have been scheduled by the action yet.");
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
        </tr>
      `,
    )
    .join("");
}

async function loadScheduledCalls() {
  renderTableLoading(aiCallbackTableBody, 5, "Loading AI callbacks...");
  renderTableLoading(executiveRequestTableBody, 6, "Loading executive requests...");

  try {
    const scheduledCalls = await scheduledCallService.listScheduledCalls();
    const aiCallbacks = scheduledCalls.filter((item) => item.type === "ai_callback");
    const executiveRequests = scheduledCalls.filter((item) => item.type === "executive_callback");
    renderAiCallbacks(aiCallbacks);
    renderExecutiveRequests(executiveRequests);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load scheduled calls.";
    renderTableError(aiCallbackTableBody, 5, message);
    renderTableError(executiveRequestTableBody, 6, message);
    showError(message);
  }
}

bootPage({
  pageKey: "scheduled-calls",
  title: pageTitles["scheduled-calls"],
  subtitle: "Action-created AI callbacks and executive call requests.",
});

loadScheduledCalls();
window.setInterval(loadScheduledCalls, frontendConfig.refreshIntervals.scheduledCallsMs);
