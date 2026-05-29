import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { confirmDialog, promptDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { callbackService } from "./services/callbackService.js";
import {
  escapeHtml,
  formatDateTime,
  formatStatusLabel,
  truncateText,
} from "./utils/formatter.js";
import {
  collectFormValues,
  requireFields,
  toIsoRangeEnd,
  toIsoRangeStart,
  validatePhoneE164,
} from "./utils/validation.js";
import { showError, showSuccess } from "./utils/notifications.js";

const callbackForm = document.getElementById("callback-form");
const callbackFormMessage = document.getElementById("callback-form-message");
const callbackSummaryPanel = document.getElementById("callback-summary-panel");
const createCallbackButton = document.getElementById("create-callback-button");
const callbackFiltersForm = document.getElementById("callback-filters");
const callbackDashboardMessage = document.getElementById("callback-dashboard-message");
const callbackTableBody = document.getElementById("callback-table-body");
const refreshCallbacksButton = document.getElementById("refresh-callbacks-button");
const clearFiltersButton = document.getElementById("clear-filters-button");

let allCallbacks = [];

function getFilterValue(fieldName) {
  const field = callbackFiltersForm.elements.namedItem(fieldName);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
    return field.value || "";
  }
  return "";
}

function renderMessage(target, type, message) {
  target.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

function clearMessage(target) {
  target.innerHTML = "";
}

function setCreateLoadingState(isLoading) {
  createCallbackButton.disabled = isLoading;
  createCallbackButton.textContent = isLoading ? "Creating Callback..." : "Create Callback";
}

function buildServerFilters() {
  return {
    status: getFilterValue("status") || undefined,
    priority: getFilterValue("priority") || undefined,
    source: getFilterValue("source") || undefined,
    date_from: toIsoRangeStart(getFilterValue("date_from")),
    date_to: toIsoRangeEnd(getFilterValue("date_to")),
  };
}

function applyClientFilters(callbacks) {
  const search = String(getFilterValue("search")).trim().toLowerCase();
  if (!search) {
    return callbacks;
  }

  return callbacks.filter((callback) => {
    const haystack = [
      callback.lead_name,
      callback.phone,
      callback.callback_reason,
      callback.requested_time_raw,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function buildRowActions(callback) {
  const actions = [];
  if (!["completed", "cancelled", "missed"].includes(callback.status)) {
    actions.push(`<button class="button secondary small" type="button" data-action="execute" data-callback-id="${callback.callback_id}">Execute Now</button>`);
    actions.push(`<button class="button ghost small" type="button" data-action="reschedule" data-callback-id="${callback.callback_id}">Reschedule</button>`);
    actions.push(`<button class="button ghost small" type="button" data-action="cancel" data-callback-id="${callback.callback_id}">Cancel</button>`);
  }
  if (!["queued", "in_progress"].includes(callback.status)) {
    actions.push(`<button class="button ghost small danger-outline" type="button" data-action="delete" data-callback-id="${callback.callback_id}">Delete</button>`);
  }
  return actions.join("");
}

function renderCallbackTable(callbacks) {
  if (!callbacks.length) {
    renderTableEmpty(callbackTableBody, 8, "No callbacks matched the current filters.");
    return;
  }

  callbackTableBody.innerHTML = callbacks
    .map(
      (callback) => `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(callback.lead_name)}</strong>
              <span class="table-subtext">${escapeHtml(truncateText(callback.callback_reason, 80))}</span>
            </div>
          </td>
          <td>${escapeHtml(callback.phone)}</td>
          <td>
            <div>${escapeHtml(formatDateTime(callback.normalized_callback_time))}</div>
            <div class="table-subtext">${escapeHtml(callback.requested_time_raw)}</div>
          </td>
          <td><span class="status-pill ${escapeHtml(callback.priority)}">${escapeHtml(callback.priority)}</span></td>
          <td>${escapeHtml(callback.source)}</td>
          <td><span class="status-pill ${escapeHtml(callback.status)}">${escapeHtml(formatStatusLabel(callback.status))}</span></td>
          <td>${callback.retry_count}</td>
          <td><div class="table-actions">${buildRowActions(callback)}</div></td>
        </tr>
      `,
    )
    .join("");
}

function renderSummary(callbacks) {
  const scheduled = callbacks.filter((callback) => callback.status === "scheduled").length;
  const active = callbacks.filter((callback) => ["queued", "in_progress"].includes(callback.status)).length;
  const completed = callbacks.filter((callback) => callback.status === "completed").length;
  const highPriority = callbacks.filter((callback) => callback.priority === "high").length;

  callbackSummaryPanel.innerHTML = `
    <div class="card-grid">
      <div class="stat-card"><span class="stat-label">Scheduled</span><span class="stat-value">${scheduled}</span></div>
      <div class="stat-card"><span class="stat-label">Active</span><span class="stat-value">${active}</span></div>
      <div class="stat-card"><span class="stat-label">Completed</span><span class="stat-value">${completed}</span></div>
      <div class="stat-card"><span class="stat-label">High Priority</span><span class="stat-value">${highPriority}</span></div>
    </div>
  `;
}

function collectCallbackPayload() {
  const payload = collectFormValues(callbackForm);
  requireFields(payload, {
    lead_name: "Lead Name",
    phone: "Phone",
    callback_reason: "Reason",
    requested_time_raw: "Requested Time",
  });

  if (!validatePhoneE164(payload.phone)) {
    throw new Error("Phone number must be in E.164 format, for example +919999999999.");
  }

  if (!payload.priority) {
    delete payload.priority;
  }
  if (!payload.notes.trim()) {
    delete payload.notes;
  }
  return payload;
}

async function loadCallbacks() {
  renderTableLoading(callbackTableBody, 8, "Loading callbacks...");

  try {
    allCallbacks = await callbackService.listCallbacks(buildServerFilters());
    const filteredCallbacks = applyClientFilters(allCallbacks);
    renderCallbackTable(filteredCallbacks);
    renderSummary(filteredCallbacks);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load callbacks.";
    renderTableError(callbackTableBody, 8, message);
    callbackSummaryPanel.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
  }
}

async function handleCallbackAction(action, callbackId) {
  clearMessage(callbackDashboardMessage);

  try {
    if (action === "execute") {
      await callbackService.executeCallback(callbackId);
      renderMessage(callbackDashboardMessage, "success", "Callback queued for immediate execution.");
      showSuccess("Callback queued for execution.");
    } else if (action === "reschedule") {
      const requestedTimeRaw = await promptDialog({
        title: "Reschedule callback",
        label: "Enter the new callback time",
        placeholder: "tomorrow 5 PM",
        confirmLabel: "Reschedule",
      });
      if (!requestedTimeRaw) {
        return;
      }
      await callbackService.rescheduleCallback(callbackId, { requested_time_raw: requestedTimeRaw });
      renderMessage(callbackDashboardMessage, "success", "Callback rescheduled successfully.");
      showSuccess("Callback rescheduled.");
    } else if (action === "cancel") {
      const confirmed = await confirmDialog({
        title: "Cancel callback",
        message: "This will cancel the callback without deleting its record. Continue?",
      });
      if (!confirmed) {
        return;
      }
      await callbackService.updateCallback(callbackId, { status: "cancelled" });
      renderMessage(callbackDashboardMessage, "success", "Callback cancelled successfully.");
      showSuccess("Callback cancelled.");
    } else if (action === "delete") {
      const confirmed = await confirmDialog({
        title: "Delete callback",
        message: "Delete this callback record permanently?",
        confirmLabel: "Delete callback",
        confirmVariant: "danger",
      });
      if (!confirmed) {
        return;
      }
      await callbackService.deleteCallback(callbackId);
      renderMessage(callbackDashboardMessage, "success", "Callback deleted successfully.");
      showSuccess("Callback deleted.");
    }

    await loadCallbacks();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to update the callback.";
    renderMessage(callbackDashboardMessage, "error", message);
    showError(message);
  }
}

callbackForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage(callbackFormMessage);
  setCreateLoadingState(true);

  try {
    const payload = collectCallbackPayload();
    const callback = await callbackService.createCallback(payload);
    renderMessage(
      callbackFormMessage,
      "success",
      `Callback ${callback.callback_id} scheduled for ${formatDateTime(callback.normalized_callback_time)}.`,
    );
    showSuccess("Callback created successfully.");
    callbackForm.reset();
    await loadCallbacks();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to create callback.";
    renderMessage(callbackFormMessage, "error", message);
    showError(message);
  } finally {
    setCreateLoadingState(false);
  }
});

callbackForm.addEventListener("reset", () => {
  clearMessage(callbackFormMessage);
});

callbackFiltersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadCallbacks();
});

clearFiltersButton.addEventListener("click", async () => {
  callbackFiltersForm.reset();
  await loadCallbacks();
});

refreshCallbacksButton.addEventListener("click", async () => {
  await loadCallbacks();
  showSuccess("Callback queue refreshed.");
});

callbackTableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  await handleCallbackAction(button.dataset.action, button.dataset.callbackId);
});

bootPage({
  pageKey: "callbacks",
  title: pageTitles.callbacks,
  subtitle: "Create, filter, reschedule, cancel, and execute smart callbacks.",
});

loadCallbacks();
window.setInterval(loadCallbacks, frontendConfig.refreshIntervals.callbacksMs);
