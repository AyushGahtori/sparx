import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { confirmDialog, showContentDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { callService } from "./services/callService.js?v=operator-complete";
import { campaignService } from "./services/campaignService.js";
import { navigateTo } from "./router.js";
import {
  escapeHtml,
  formatDateTime,
  formatDuration,
  formatScore,
  formatStatusLabel,
} from "./utils/formatter.js";
import { showError, showInfo, showSuccess } from "./utils/notifications.js";

const filtersForm = document.getElementById("call-history-filters");
const clearFiltersButton = document.getElementById("clear-call-history-filters-button");
const refreshButton = document.getElementById("refresh-call-history-button");
const messageRoot = document.getElementById("call-history-message");
const tableBody = document.getElementById("call-history-table-body");
const campaignFilter = document.getElementById("call-campaign-filter");

let allCalls = [];
let campaignMap = new Map();
let isCallsRefreshing = false;
const ACTIVE_CALL_STATUSES = ["initiated", "ringing", "answered", "in_progress"];

function getFilterValue(fieldName) {
  const field = filtersForm.elements.namedItem(fieldName);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
    return field.value || "";
  }
  return "";
}

function renderMessage(type, message) {
  messageRoot.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

function clearMessage() {
  messageRoot.innerHTML = "";
}

function getCampaignName(campaignId) {
  if (!campaignId) {
    return "Manual";
  }
  return campaignMap.get(campaignId) || campaignId;
}

function buildDetailTranscript(transcript) {
  if (!transcript?.length) {
    return "<div class=\"empty-state\">No transcript is stored for this call.</div>";
  }

  return `
    <div class="transcript-list">
      ${transcript
        .slice(0, 12)
        .map(
          (entry) => `
            <div class="transcript-entry">
              <div class="transcript-meta">
                <strong>${escapeHtml(entry.speaker)}</strong>
                <span>${escapeHtml(formatDateTime(entry.timestamp))}</span>
              </div>
              <div>${escapeHtml(entry.text)}</div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function openCallDetail(call) {
  showContentDialog({
    title: `${call.lead_name} call details`,
    bodyHtml: `
      <div class="card-grid">
        <div class="stat-card"><span class="stat-label">Status</span><span class="stat-value">${escapeHtml(formatStatusLabel(call.status))}</span></div>
        <div class="stat-card"><span class="stat-label">Duration</span><span class="stat-value">${escapeHtml(formatDuration(call.duration))}</span></div>
        <div class="stat-card"><span class="stat-label">Lead Type</span><span class="stat-value">${escapeHtml(call.lead_type || "-")}</span></div>
        <div class="stat-card"><span class="stat-label">AI Score</span><span class="stat-value">${formatScore(call.ai_score)}</span></div>
      </div>
      <div class="detail-list" style="margin-top: 1rem;">
        <div class="detail-row"><span class="detail-label">Phone</span><span>${escapeHtml(call.phone)}</span></div>
        <div class="detail-row"><span class="detail-label">Call Type</span><span>${escapeHtml(call.call_type)}</span></div>
        <div class="detail-row"><span class="detail-label">Campaign</span><span>${escapeHtml(getCampaignName(call.campaign_id))}</span></div>
        <div class="detail-row"><span class="detail-label">Agent</span><span>${escapeHtml(call.agent_name)}</span></div>
        <div class="detail-row"><span class="detail-label">Objective</span><span>${escapeHtml(call.call_objective)}</span></div>
        <div class="detail-row"><span class="detail-label">Summary</span><span>${escapeHtml(call.summary || "No AI summary available yet.")}</span></div>
        <div class="detail-row"><span class="detail-label">Next Action</span><span>${escapeHtml(call.next_action || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Outcome</span><span>${escapeHtml(call.call_outcome || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Notes</span><span>${escapeHtml(call.notes || "No notes stored.")}</span></div>
      </div>
      <h3 style="margin-top: 1.25rem;">Transcript Preview</h3>
      ${buildDetailTranscript(call.transcript)}
    `,
    footerHtml: `<button class="button ghost" type="button" data-modal-close="true">Close</button>`,
  });
}

function applyFilters(calls) {
  const search = String(getFilterValue("search")).trim().toLowerCase();
  const status = getFilterValue("status");
  const callType = getFilterValue("call_type");
  const campaignId = getFilterValue("campaign_id");
  const dateFromValue = getFilterValue("date_from");
  const dateToValue = getFilterValue("date_to");
  const dateFrom = dateFromValue ? new Date(`${dateFromValue}T00:00:00`) : null;
  const dateTo = dateToValue ? new Date(`${dateToValue}T23:59:59`) : null;

  return calls.filter((call) => {
    if (status && call.status !== status) {
      return false;
    }
    if (callType && call.call_type !== callType) {
      return false;
    }
    if (campaignId && call.campaign_id !== campaignId) {
      return false;
    }

    const callDate = new Date(call.ended_at || call.created_at || 0);
    if (dateFrom && callDate < dateFrom) {
      return false;
    }
    if (dateTo && callDate > dateTo) {
      return false;
    }

    if (!search) {
      return true;
    }

    const haystack = [
      call.lead_name,
      call.phone,
      call.company,
      call.city,
      call.status,
      call.call_outcome,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function renderRows(calls) {
  if (!calls.length) {
    renderTableEmpty(tableBody, 9, "No calls matched the current filters.");
    return;
  }

  tableBody.innerHTML = calls
    .map((call) => {
      const canDelete =
        call.call_type === "individual" &&
        !call.campaign_id &&
        !call.contact_id &&
        !call.callback_id &&
        !ACTIVE_CALL_STATUSES.includes(call.status);
      const canMarkCompleted = call.call_type === "individual" && ACTIVE_CALL_STATUSES.includes(call.status);

      return `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(call.lead_name)}</strong>
              <span class="table-subtext">${escapeHtml(call.phone)}</span>
            </div>
          </td>
          <td>${escapeHtml(call.call_type)}</td>
          <td>${escapeHtml(getCampaignName(call.campaign_id))}</td>
          <td><span class="status-pill ${escapeHtml(call.status)}">${escapeHtml(formatStatusLabel(call.status))}</span></td>
          <td>${escapeHtml(formatDuration(call.duration, "-"))}</td>
          <td>${escapeHtml(formatDateTime(call.ended_at || call.created_at))}</td>
          <td>${call.lead_type ? `<span class="status-pill ${escapeHtml(call.lead_type)}">${escapeHtml(call.lead_type)}</span>` : "-"}</td>
          <td>${call.call_outcome ? `<span class="status-pill ${escapeHtml(call.call_outcome)}">${escapeHtml(formatStatusLabel(call.call_outcome))}</span>` : "-"}</td>
          <td>
            <div class="table-actions">
              <button class="button secondary small" type="button" data-action="view" data-call-id="${call.call_id}">View Summary</button>
              <button class="button ghost small" type="button" data-action="retry" data-call-id="${call.call_id}">Retry Call</button>
              ${
                canMarkCompleted
                  ? `<button class="button ghost small" type="button" data-action="complete" data-call-id="${call.call_id}">Mark Completed</button>`
                  : ""
              }
              ${
                canDelete
                  ? `<button class="button ghost small danger-outline" type="button" data-action="delete" data-call-id="${call.call_id}">Delete</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function loadCampaignMap() {
  try {
    const campaigns = await campaignService.listCampaigns();
    campaignMap = new Map(campaigns.map((campaign) => [campaign.campaign_id, campaign.campaign_name]));
    campaignFilter.innerHTML = `
      <option value="">All</option>
      ${campaigns
        .map((campaign) => `<option value="${escapeHtml(campaign.campaign_id)}">${escapeHtml(campaign.campaign_name)}</option>`)
        .join("")}
    `;
  } catch {
    campaignMap = new Map();
    campaignFilter.innerHTML = `<option value="">All</option>`;
  }
}

async function loadCalls({ showLoading = true } = {}) {
  if (isCallsRefreshing) {
    return;
  }
  isCallsRefreshing = true;

  if (showLoading) {
    renderTableLoading(tableBody, 9, "Loading calls...");
  }

  try {
    allCalls = await callService.listCalls();
    renderRows(applyFilters(allCalls));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load call history.";
    if (showLoading) {
      renderTableError(tableBody, 9, message);
    }
    showError(message);
  } finally {
    isCallsRefreshing = false;
  }
}

async function handleAction(action, callId) {
  clearMessage();

  try {
    const call = allCalls.find((item) => item.call_id === callId) || (await callService.getCall(callId));

    if (action === "view") {
      openCallDetail(call);
      return;
    }

    if (action === "retry") {
      showInfo("Lead details were sent to the manual call form for retry.");
      navigateTo("manual-call", {
        lead_name: call.lead_name,
        phone: call.phone,
        company: call.company || "",
        city: call.city || "",
        role: call.role || "",
        interest: call.interest || "",
        agent_id: call.agent_id,
        call_objective: call.call_objective,
        additional_context: call.additional_context || call.notes || "",
        language: call.language,
        priority: call.priority,
      });
      return;
    }

    if (action === "delete") {
      const confirmed = await confirmDialog({
        title: "Delete call record",
        message: "Delete this standalone manual call record from Firestore?",
        confirmLabel: "Delete call",
        confirmVariant: "danger",
      });
      if (!confirmed) {
        return;
      }
      await callService.deleteCall(callId);
      renderMessage("success", "Call record deleted successfully.");
      showSuccess("Call record deleted.");
      await loadCalls({ showLoading: false });
    }

    if (action === "complete") {
      const confirmed = await confirmDialog({
        title: "Mark call completed",
        message: "Mark this stuck manual call as completed so the number can be called again immediately?",
        confirmLabel: "Mark completed",
      });
      if (!confirmed) {
        return;
      }
      await callService.updateCallStatus(callId, {
        status: "completed",
        notes: "Manually marked completed by operator.",
      });
      renderMessage("success", "Call marked completed successfully.");
      showSuccess("Call marked completed.");
      await loadCalls({ showLoading: false });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to complete the call history action.";
    renderMessage("error", message);
    showError(message);
  }
}

filtersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  renderRows(applyFilters(allCalls));
});

clearFiltersButton.addEventListener("click", () => {
  filtersForm.reset();
  renderRows(applyFilters(allCalls));
});

refreshButton.addEventListener("click", async () => {
  await loadCalls({ showLoading: true });
  showSuccess("Call history refreshed.");
});

tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  await handleAction(button.dataset.action, button.dataset.callId);
});

bootPage({
  pageKey: "call-history",
  title: pageTitles["call-history"],
  subtitle: "Search across stored call records and reopen leads in the manual flow.",
});

loadCampaignMap();
loadCalls({ showLoading: true });
window.setInterval(() => loadCalls({ showLoading: false }), frontendConfig.refreshIntervals.callHistoryMs);
