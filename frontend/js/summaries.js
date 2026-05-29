import { bootPage } from "./app.js";
import { pageTitles, frontendConfig } from "./config.js";
import { confirmDialog, showContentDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { campaignService } from "./services/campaignService.js";
import { summaryService } from "./services/summaryService.js";
import {
  escapeHtml,
  formatDateTime,
  formatScore,
  formatStatusLabel,
  truncateText,
} from "./utils/formatter.js";
import { toIsoRangeEnd, toIsoRangeStart } from "./utils/validation.js";
import { showError, showSuccess } from "./utils/notifications.js";

const summaryFiltersForm = document.getElementById("summary-filters");
const summariesMessage = document.getElementById("summaries-message");
const summariesTableBody = document.getElementById("summaries-table-body");
const refreshSummariesButton = document.getElementById("refresh-summaries-button");
const exportSummariesButton = document.getElementById("export-summaries-button");
const clearSummaryFiltersButton = document.getElementById("clear-summary-filters-button");
const campaignFilter = document.getElementById("filter-campaign-id");

let currentSummaries = [];
let currentDetail = null;

function getFilterValue(fieldName) {
  const field = summaryFiltersForm.elements.namedItem(fieldName);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
    return field.value || "";
  }
  return "";
}

function renderMessage(type, message) {
  summariesMessage.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

function clearMessage() {
  summariesMessage.innerHTML = "";
}

function buildServerFilters() {
  return {
    date_from: toIsoRangeStart(getFilterValue("date_from")),
    date_to: toIsoRangeEnd(getFilterValue("date_to")),
    campaign_id: getFilterValue("campaign_id") || undefined,
    lead_type: getFilterValue("lead_type") || undefined,
    outcome: getFilterValue("outcome") || undefined,
    sentiment: getFilterValue("sentiment") || undefined,
  };
}

function applySearchFilter(summaries) {
  const search = String(getFilterValue("search")).trim().toLowerCase();
  if (!search) {
    return summaries;
  }

  return summaries.filter((summary) => {
    const haystack = [
      summary.lead_name,
      summary.phone,
      summary.summary,
      summary.next_action,
      summary.call_outcome,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function renderSummariesTable(summaries) {
  if (!summaries.length) {
    renderTableEmpty(summariesTableBody, 8, "No summaries matched the current filters.");
    return;
  }

  summariesTableBody.innerHTML = summaries
    .map(
      (summary) => `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(summary.lead_name)}</strong>
              <span class="table-subtext">${escapeHtml(summary.phone)}</span>
            </div>
          </td>
          <td>${escapeHtml(truncateText(summary.summary || summary.ai_error || formatStatusLabel(summary.ai_processing_status), 120))}</td>
          <td>${summary.sentiment ? `<span class="status-pill ${escapeHtml(summary.sentiment)}">${escapeHtml(summary.sentiment)}</span>` : "-"}</td>
          <td>${summary.lead_type ? `<span class="status-pill ${escapeHtml(summary.lead_type)}">${escapeHtml(summary.lead_type)}</span>` : "-"}</td>
          <td>${summary.call_outcome ? `<span class="status-pill ${escapeHtml(summary.call_outcome)}">${escapeHtml(formatStatusLabel(summary.call_outcome))}</span>` : "-"}</td>
          <td>${formatScore(summary.ai_score)}</td>
          <td>${escapeHtml(truncateText(summary.next_action || "-", 70))}</td>
          <td>
            <div class="table-actions">
              <button class="button secondary small" type="button" data-action="view" data-call-id="${summary.call_id}">View Details</button>
              <button class="button ghost small danger-outline" type="button" data-action="delete" data-call-id="${summary.call_id}">Delete</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function buildTranscriptMarkup(entries) {
  if (!entries.length) {
    return "<div class=\"empty-state\">No transcript is available for this call.</div>";
  }

  return `
    <div class="transcript-list">
      ${entries
        .slice(0, 14)
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

function openSummaryDetail(detail) {
  currentDetail = detail;
  showContentDialog({
    title: `${detail.lead_name} summary`,
    bodyHtml: `
      <div class="card-grid">
        <div class="stat-card"><span class="stat-label">Sentiment</span><span class="stat-value">${escapeHtml(detail.sentiment || "-")}</span><span class="stat-footnote">${detail.sentiment_confidence ? `${Math.round(detail.sentiment_confidence * 100)}% confidence` : ""}</span></div>
        <div class="stat-card"><span class="stat-label">Lead Type</span><span class="stat-value">${escapeHtml(detail.lead_type || "-")}</span><span class="stat-footnote">${detail.lead_confidence ? `${Math.round(detail.lead_confidence * 100)}% confidence` : ""}</span></div>
        <div class="stat-card"><span class="stat-label">Outcome</span><span class="stat-value">${escapeHtml(detail.call_outcome || "-")}</span></div>
        <div class="stat-card"><span class="stat-label">AI Score</span><span class="stat-value">${formatScore(detail.ai_score)}</span></div>
      </div>

      <div class="detail-list" style="margin-top: 1rem;">
        <div class="detail-row"><span class="detail-label">Summary</span><span>${escapeHtml(detail.summary || "No summary available.")}</span></div>
        <div class="detail-row"><span class="detail-label">Next Action</span><span>${escapeHtml(detail.next_action || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Short Notes</span><span>${escapeHtml(detail.short_notes || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Lead Reason</span><span>${escapeHtml(detail.lead_reason || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Outcome Reason</span><span>${escapeHtml(detail.outcome_reason || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Objections</span><span>${detail.objections.length ? detail.objections.map((item) => escapeHtml(item)).join(", ") : "No objections detected."}</span></div>
      </div>

      <h3 style="margin-top: 1.25rem;">Transcript Preview</h3>
      ${buildTranscriptMarkup(detail.transcript)}
    `,
    footerHtml: `<button class="button ghost" type="button" data-modal-close="true">Close</button>`,
  });
}

async function loadCampaignOptions() {
  try {
    const campaigns = await campaignService.listCampaigns();
    campaignFilter.innerHTML = `
      <option value="">All</option>
      ${campaigns
        .map((campaign) => `<option value="${escapeHtml(campaign.campaign_id)}">${escapeHtml(campaign.campaign_name)}</option>`)
        .join("")}
    `;
  } catch {
    campaignFilter.innerHTML = `<option value="">All</option>`;
  }
}

async function loadSummaries() {
  renderTableLoading(summariesTableBody, 8, "Loading summaries...");

  try {
    const summaries = await summaryService.listSummaries(buildServerFilters());
    currentSummaries = applySearchFilter(summaries);
    clearMessage();
    renderSummariesTable(currentSummaries);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load summaries.";
    renderMessage("error", message);
    renderTableError(summariesTableBody, 8, message);
  }
}

async function handleSummaryAction(action, callId) {
  clearMessage();

  try {
    if (action === "view") {
      const detail = await summaryService.getSummary(callId);
      openSummaryDetail(detail);
      return;
    }

    if (action === "delete") {
      const confirmed = await confirmDialog({
        title: "Delete AI summary",
        message: "This clears the stored post-call intelligence for the selected call. Continue?",
        confirmLabel: "Delete summary",
        confirmVariant: "danger",
      });
      if (!confirmed) {
        return;
      }
      await summaryService.deleteSummary(callId);
      renderMessage("success", "AI summary deleted successfully.");
      showSuccess("AI summary deleted.");
      currentDetail = currentDetail?.call_id === callId ? null : currentDetail;
      await loadSummaries();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Summary action failed.";
    renderMessage("error", message);
    showError(message);
  }
}

function exportJson() {
  const payload = currentDetail || currentSummaries;
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = currentDetail ? `${currentDetail.call_id}-summary.json` : "sparx-summaries.json";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  showSuccess("Summary export downloaded.");
}

summaryFiltersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadSummaries();
});

clearSummaryFiltersButton.addEventListener("click", async () => {
  summaryFiltersForm.reset();
  await loadSummaries();
});

refreshSummariesButton.addEventListener("click", async () => {
  await loadSummaries();
  showSuccess("Summaries refreshed.");
});

exportSummariesButton.addEventListener("click", () => {
  exportJson();
});

summariesTableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  await handleSummaryAction(button.dataset.action, button.dataset.callId);
});

bootPage({
  pageKey: "summaries",
  title: pageTitles.summaries,
  subtitle: "Review Gemma-generated summaries, classifications, and transcript evidence.",
});

loadCampaignOptions();
loadSummaries();
window.setInterval(loadSummaries, frontendConfig.refreshIntervals.summariesMs);
