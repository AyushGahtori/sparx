import { bootPage } from "./app.js";
import { pageTitles, frontendConfig } from "./config.js";
import { confirmDialog, showContentDialog } from "./components/modal.js";
import { emptyState, errorState, loadingState } from "./components/loading.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { campaignService } from "./services/campaignService.js";
import { callService } from "./services/callService.js";
import { scheduledCallService } from "./services/scheduledCallService.js?v=campaign-schedules";
import {
  escapeHtml,
  formatDateTime,
  formatPercent,
  formatStatusLabel,
  toLocalDateTimeInputValue,
} from "./utils/formatter.js";
import { collectFormValues, normalizeOptionalString, requireFields } from "./utils/validation.js";
import { showError, showSuccess } from "./utils/notifications.js";

const form = document.getElementById("campaign-form");
const formMessage = document.getElementById("campaign-form-message");
const agentSelect = document.getElementById("agent-id");
const csvFileInput = document.getElementById("csv-file");
const agentInstructionsInput = document.getElementById("notes");
const agentInstructionsFileInput = document.getElementById("agent-instructions-file");
const previewPanel = document.getElementById("csv-preview-panel");
const createButton = document.getElementById("create-campaign-button");
const scheduleTypeSelect = document.getElementById("schedule-type");
const scheduledAtWrapper = document.getElementById("scheduled-at-wrapper");
const scheduledAtInput = document.getElementById("scheduled-at");
const aiCallbackMaxDateInput = document.getElementById("ai-callback-max-date");
const executiveCallbackMaxDateInput = document.getElementById("executive-callback-max-date");
const filtersForm = document.getElementById("campaign-filters");
const clearFiltersButton = document.getElementById("clear-campaign-filters-button");
const tableBody = document.getElementById("campaign-table-body");
const refreshButton = document.getElementById("refresh-campaigns-button");
const dashboardMessage = document.getElementById("campaign-dashboard-message");
const campaignAiCallbackTableBody = document.getElementById("campaign-ai-callback-table-body");
const campaignExecutiveRequestTableBody = document.getElementById("campaign-executive-request-table-body");
const campaignAiCallbackCount = document.getElementById("campaign-ai-callback-count");
const campaignExecutiveRequestCount = document.getElementById("campaign-executive-request-count");
const campaignScheduleMessage = document.getElementById("campaign-schedule-message");

let previewContacts = [];
let allCampaigns = [];
let agentPromptMap = new Map();
let activeAgentDefaultPrompt = "";
let instructionsEditedByOperator = false;
let activeSearch = "";
let activeStatus = "";

function getFilterValue(fieldName) {
  const field = filtersForm.elements.namedItem(fieldName);
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
  createButton.disabled = isLoading;
  createButton.textContent = isLoading ? "Creating Campaign..." : "Create Campaign";
}

function toggleScheduledField() {
  const isScheduled = scheduleTypeSelect.value === "scheduled";
  scheduledAtWrapper.classList.toggle("hidden", !isScheduled);
  scheduledAtInput.required = isScheduled;
}

function toDateInputValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateDaysFromNow(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return toDateInputValue(date);
}

function setSchedulingDateDefaults() {
  const today = toDateInputValue(new Date());
  const defaultMaxDate = dateDaysFromNow(30);
  [aiCallbackMaxDateInput, executiveCallbackMaxDateInput].forEach((input) => {
    input.min = today;
    if (!input.value) {
      input.value = defaultMaxDate;
    }
  });
}

function resetPreview() {
  previewContacts = [];
  previewPanel.innerHTML = emptyState("Upload a CSV to preview valid, invalid, and duplicate rows.");
}

function getSelectedAgentDefaultPrompt() {
  return agentPromptMap.get(agentSelect.value) || "";
}

function applySelectedAgentPrompt({ force = false } = {}) {
  const nextPrompt = getSelectedAgentDefaultPrompt();
  const currentPrompt = agentInstructionsInput.value.trim();
  const canReplacePrompt = force || !instructionsEditedByOperator || currentPrompt === activeAgentDefaultPrompt.trim();
  activeAgentDefaultPrompt = nextPrompt;
  if (canReplacePrompt) {
    agentInstructionsInput.value = nextPrompt;
    instructionsEditedByOperator = false;
  }
}

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

function getCampaignName(campaignId) {
  if (!campaignId) {
    return "Unknown campaign";
  }
  return allCampaigns.find((campaign) => campaign.campaign_id === campaignId)?.campaign_name || campaignId;
}

function renderCampaignAiCallbacks(items) {
  campaignAiCallbackCount.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(campaignAiCallbackTableBody, 6, "No campaign AI callbacks have been scheduled yet.");
    return;
  }

  campaignAiCallbackTableBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(getCampaignName(item.campaign_id))}</td>
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

function renderCampaignExecutiveRequests(items) {
  campaignExecutiveRequestCount.textContent = String(items.length);
  if (!items.length) {
    renderTableEmpty(campaignExecutiveRequestTableBody, 7, "No campaign executive call requests have been scheduled yet.");
    return;
  }

  campaignExecutiveRequestTableBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(getCampaignName(item.campaign_id))}</td>
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

function buildPreviewMarkup(preview) {
  const rows = preview.preview_rows
    .map(
      (row) => `
        <tr>
          <td>${row.row_number}</td>
          <td>${escapeHtml(row.name || "-")}</td>
          <td>${escapeHtml(row.normalized_phone || row.phone || "-")}</td>
          <td>${escapeHtml(row.company || "-")}</td>
          <td>${escapeHtml(row.city || "-")}</td>
          <td>${escapeHtml(row.role || "-")}</td>
          <td>${escapeHtml(row.interest || "-")}</td>
          <td><span class="status-pill ${escapeHtml(row.validation_status)}">${escapeHtml(row.validation_status)}</span></td>
          <td>${escapeHtml(row.validation_message)}</td>
        </tr>
      `,
    )
    .join("");

  return `
    <div class="card-grid">
      <div class="stat-card"><span class="stat-label">Valid Contacts</span><span class="stat-value">${preview.valid_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Invalid Contacts</span><span class="stat-value">${preview.invalid_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Duplicate Contacts</span><span class="stat-value">${preview.duplicate_contacts}</span></div>
    </div>
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Phone</th>
            <th>Company</th>
            <th>City</th>
            <th>Role</th>
            <th>Interest</th>
            <th>Status</th>
            <th>Validation</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function buildCampaignActions(campaign) {
  const buttons = [];

  if (["scheduled", "failed"].includes(campaign.status)) {
    buttons.push(`<button class="button secondary small" type="button" data-action="start" data-campaign-id="${campaign.campaign_id}">Start</button>`);
  }
  if (campaign.status === "running") {
    buttons.push(`<button class="button secondary small" type="button" data-action="pause" data-campaign-id="${campaign.campaign_id}">Pause</button>`);
    buttons.push(`<button class="button ghost small" type="button" data-action="stop" data-campaign-id="${campaign.campaign_id}">Stop</button>`);
  }
  if (campaign.status === "paused") {
    buttons.push(`<button class="button secondary small" type="button" data-action="resume" data-campaign-id="${campaign.campaign_id}">Resume</button>`);
    buttons.push(`<button class="button ghost small" type="button" data-action="stop" data-campaign-id="${campaign.campaign_id}">Stop</button>`);
  }

  buttons.push(`<button class="button ghost small" type="button" data-action="details" data-campaign-id="${campaign.campaign_id}">View Details</button>`);

  if (campaign.status !== "running") {
    buttons.push(`<button class="button ghost small danger-outline" type="button" data-action="delete" data-campaign-id="${campaign.campaign_id}">Delete</button>`);
  }

  return buttons.join("");
}

function applyFilters(campaigns) {
  return campaigns.filter((campaign) => {
    if (activeStatus && campaign.status !== activeStatus) {
      return false;
    }

    if (!activeSearch) {
      return true;
    }

    const haystack = [
      campaign.campaign_name,
      campaign.campaign_type,
      campaign.call_objective,
      campaign.agent_name,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return haystack.includes(activeSearch);
  });
}

function renderCampaignRows(campaigns) {
  if (!campaigns.length) {
    renderTableEmpty(tableBody, 7, "No campaigns matched the current filters.");
    return;
  }

  tableBody.innerHTML = campaigns
    .map(
      (campaign) => `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(campaign.campaign_name)}</strong>
              <span class="table-subtext">${escapeHtml(campaign.campaign_type)}</span>
            </div>
          </td>
          <td><span class="status-pill ${escapeHtml(campaign.status)}">${escapeHtml(campaign.status)}</span></td>
          <td>
            <div>${campaign.completed_calls}/${campaign.total_contacts} completed</div>
            <div class="table-subtext">Pending: ${campaign.pending_calls} | Active: ${campaign.active_calls} | Retry: ${campaign.retry_calls}</div>
          </td>
          <td>${campaign.total_contacts}</td>
          <td>${formatPercent(campaign.success_rate)}</td>
          <td>${escapeHtml(formatDateTime(campaign.created_at))}</td>
          <td><div class="table-actions">${buildCampaignActions(campaign)}</div></td>
        </tr>
      `,
    )
    .join("");
}

async function loadAgents() {
  agentSelect.innerHTML = "<option>Loading agents...</option>";

  try {
    const agents = await callService.listAgents();
    if (!agents.length) {
      agentPromptMap = new Map();
      agentSelect.innerHTML = "<option value=''>No agents configured</option>";
      renderMessage(formMessage, "info", "No Deepgram agents are available.");
      return;
    }

    agentPromptMap = new Map(agents.map((agent) => [agent.agent_id, agent.default_prompt || ""]));
    agentSelect.innerHTML = agents
      .map(
        (agent) => `
          <option value="${escapeHtml(agent.agent_id)}">
            ${escapeHtml(agent.agent_name)} - ${escapeHtml(agent.purpose)}
          </option>
        `,
      )
      .join("");
    applySelectedAgentPrompt({ force: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load agents.";
    renderMessage(formMessage, "error", message);
    agentSelect.innerHTML = "<option value=''>Unable to load agents</option>";
  }
}

async function previewCsv(file) {
  if (!file) {
    resetPreview();
    return;
  }

  previewPanel.innerHTML = loadingState("Validating CSV upload...");

  try {
    const preview = await campaignService.previewCsv(file);
    previewContacts = preview.contacts;
    previewPanel.innerHTML = buildPreviewMarkup(preview);
    renderMessage(
      formMessage,
      "success",
      `${preview.valid_contacts} contacts are ready. ${preview.invalid_contacts} invalid and ${preview.duplicate_contacts} duplicate rows were detected.`,
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "CSV preview failed.";
    previewContacts = [];
    previewPanel.innerHTML = errorState(message);
    renderMessage(formMessage, "error", message);
  }
}

function collectCampaignPayload() {
  const payload = collectFormValues(form);
  const formData = new FormData(form);
  payload.executive_callback_allowed_weekdays = formData
    .getAll("executive_callback_allowed_weekdays")
    .map((weekday) => Number(weekday));
  requireFields(payload, {
    campaign_name: "Campaign Name",
    agent_id: "Deepgram Agent",
    campaign_type: "Campaign Type",
    call_objective: "Call Objective",
    language: "Language",
  });

  if (!previewContacts.length) {
    throw new Error("Upload and validate a CSV file before creating the campaign.");
  }
  if (!payload.executive_callback_allowed_weekdays.length) {
    throw new Error("Select at least one executive working day.");
  }

  payload.contacts = previewContacts;
  payload.notes = normalizeOptionalString(payload.notes);
  if (payload.schedule_type === "scheduled") {
    if (!payload.scheduled_at) {
      throw new Error("Please select a scheduled date and time.");
    }
    payload.scheduled_at = new Date(payload.scheduled_at).toISOString();
  } else {
    delete payload.scheduled_at;
  }
  return payload;
}

async function loadCampaigns() {
  renderTableLoading(tableBody, 7, "Loading campaigns...");

  try {
    allCampaigns = await campaignService.listCampaigns();
    renderCampaignRows(applyFilters(allCampaigns));
    await loadCampaignSchedules();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load campaigns.";
    renderTableError(tableBody, 7, message);
  }
}

async function loadCampaignSchedules() {
  renderTableLoading(campaignAiCallbackTableBody, 6, "Loading campaign AI callbacks...");
  renderTableLoading(campaignExecutiveRequestTableBody, 7, "Loading campaign executive requests...");
  clearMessage(campaignScheduleMessage);

  try {
    const scheduledCalls = await scheduledCallService.listScheduledCalls();
    const campaignSchedules = scheduledCalls.filter((item) => item.call_type === "campaign" || item.campaign_id);
    renderCampaignAiCallbacks(campaignSchedules.filter((item) => item.type === "ai_callback"));
    renderCampaignExecutiveRequests(campaignSchedules.filter((item) => item.type === "executive_callback"));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load campaign schedules.";
    renderTableError(campaignAiCallbackTableBody, 6, message);
    renderTableError(campaignExecutiveRequestTableBody, 7, message);
    renderMessage(campaignScheduleMessage, "error", message);
  }
}

async function openCampaignDetails(campaignId) {
  try {
    const [campaign, contacts] = await Promise.all([
      campaignService.getCampaign(campaignId),
      campaignService.getCampaignContacts(campaignId),
    ]);

    const contactsMarkup = contacts.length
      ? `
        <div class="table-shell compact">
          <table class="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Status</th>
                <th>Retry Count</th>
                <th>Call SID</th>
              </tr>
            </thead>
            <tbody>
              ${contacts
                .map(
                  (contact) => `
                    <tr>
                      <td>${escapeHtml(contact.name)}</td>
                      <td>${escapeHtml(contact.phone)}</td>
                      <td><span class="status-pill ${escapeHtml(contact.status)}">${escapeHtml(formatStatusLabel(contact.status))}</span></td>
                      <td>${contact.retry_count}</td>
                      <td>${escapeHtml(contact.call_sid || "-")}</td>
                    </tr>
                  `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `
      : emptyState("No contacts were stored for this campaign.");

    showContentDialog({
      title: `${campaign.campaign_name} details`,
      bodyHtml: `
        <div class="card-grid">
          <div class="stat-card"><span class="stat-label">Contacts</span><span class="stat-value">${campaign.total_contacts}</span></div>
          <div class="stat-card"><span class="stat-label">Completed</span><span class="stat-value">${campaign.completed_calls}</span></div>
          <div class="stat-card"><span class="stat-label">Answered</span><span class="stat-value">${campaign.answered_calls}</span></div>
          <div class="stat-card"><span class="stat-label">Success Rate</span><span class="stat-value">${formatPercent(campaign.success_rate)}</span></div>
        </div>
        <div class="key-value-grid" style="margin-top: 1rem;">
          <div><strong>Agent:</strong> ${escapeHtml(campaign.agent_name)}</div>
          <div><strong>Status:</strong> ${escapeHtml(campaign.status)}</div>
          <div><strong>Objective:</strong> ${escapeHtml(campaign.call_objective)}</div>
          <div><strong>Scheduled:</strong> ${escapeHtml(formatDateTime(campaign.scheduled_at))}</div>
          <div><strong>Agent Instructions:</strong> ${escapeHtml(campaign.notes || "No campaign-specific instructions")}</div>
          <div><strong>Priority:</strong> ${escapeHtml(campaign.priority)}</div>
        </div>
        <h3 style="margin-top: 1.25rem;">Contacts</h3>
        ${contactsMarkup}
      `,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load campaign details.";
    renderMessage(dashboardMessage, "error", message);
    showError(message);
  }
}

async function handleCampaignAction(action, campaignId) {
  clearMessage(dashboardMessage);

  try {
    if (action === "details") {
      await openCampaignDetails(campaignId);
      return;
    }

    if (action === "delete") {
      const confirmed = await confirmDialog({
        title: "Delete campaign",
        message: "This will remove the campaign and its stored contact queue. Continue?",
        confirmLabel: "Delete campaign",
        confirmVariant: "danger",
      });
      if (!confirmed) {
        return;
      }
      await campaignService.deleteCampaign(campaignId);
      renderMessage(dashboardMessage, "success", "Campaign deleted successfully.");
      showSuccess("Campaign deleted.");
    } else if (action === "stop") {
      const confirmed = await confirmDialog({
        title: "Stop campaign",
        message: "This will halt any further dispatching for the campaign. Continue?",
        confirmLabel: "Stop campaign",
      });
      if (!confirmed) {
        return;
      }
      await campaignService.stopCampaign(campaignId);
      renderMessage(dashboardMessage, "success", "Campaign stopped successfully.");
      showSuccess("Campaign stopped.");
    } else if (action === "start") {
      await campaignService.startCampaign(campaignId);
      renderMessage(dashboardMessage, "success", "Campaign started successfully.");
      showSuccess("Campaign started.");
    } else if (action === "pause") {
      await campaignService.pauseCampaign(campaignId);
      renderMessage(dashboardMessage, "success", "Campaign paused successfully.");
      showSuccess("Campaign paused.");
    } else if (action === "resume") {
      await campaignService.resumeCampaign(campaignId);
      renderMessage(dashboardMessage, "success", "Campaign resumed successfully.");
      showSuccess("Campaign resumed.");
    }

    await loadCampaigns();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Campaign action failed.";
    renderMessage(dashboardMessage, "error", message);
    showError(message);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage(formMessage);
  setCreateLoadingState(true);

  try {
    const payload = collectCampaignPayload();
    const campaign = await campaignService.createCampaign(payload);
    renderMessage(formMessage, "success", `Campaign ${campaign.campaign_name} was created successfully.`);
    showSuccess(`Campaign ${campaign.campaign_name} created.`);
    form.reset();
    scheduledAtInput.value = toLocalDateTimeInputValue();
    setSchedulingDateDefaults();
    toggleScheduledField();
    resetPreview();
    applySelectedAgentPrompt({ force: true });
    await loadCampaigns();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to create the campaign.";
    renderMessage(formMessage, "error", message);
    showError(message);
  } finally {
    setCreateLoadingState(false);
  }
});

form.addEventListener("reset", () => {
  clearMessage(formMessage);
  window.setTimeout(() => {
    scheduledAtInput.value = toLocalDateTimeInputValue();
    setSchedulingDateDefaults();
    toggleScheduledField();
    applySelectedAgentPrompt({ force: true });
  }, 0);
  resetPreview();
});

csvFileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files || [];
  await previewCsv(file);
});

agentInstructionsInput.addEventListener("input", () => {
  instructionsEditedByOperator = agentInstructionsInput.value.trim() !== activeAgentDefaultPrompt.trim();
});

agentInstructionsFileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files || [];
  if (!file) {
    return;
  }
  if (!file.name.toLowerCase().endsWith(".txt") && file.type !== "text/plain") {
    renderMessage(formMessage, "error", "Upload a plain .txt file for agent instructions.");
    agentInstructionsFileInput.value = "";
    return;
  }
  const text = await file.text();
  agentInstructionsInput.value = text.trim();
  instructionsEditedByOperator = agentInstructionsInput.value.trim() !== activeAgentDefaultPrompt.trim();
  renderMessage(formMessage, "success", "Agent instructions were loaded from the text file.");
});

agentSelect.addEventListener("change", () => {
  applySelectedAgentPrompt();
});

scheduleTypeSelect.addEventListener("change", toggleScheduledField);

filtersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  activeSearch = String(getFilterValue("search")).trim().toLowerCase();
  activeStatus = String(getFilterValue("status"));
  renderCampaignRows(applyFilters(allCampaigns));
});

clearFiltersButton.addEventListener("click", () => {
  filtersForm.reset();
  activeSearch = "";
  activeStatus = "";
  renderCampaignRows(applyFilters(allCampaigns));
});

tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }

  await handleCampaignAction(button.dataset.action, button.dataset.campaignId);
});

refreshButton.addEventListener("click", async () => {
  await loadCampaigns();
  showSuccess("Campaign list refreshed.");
});

bootPage({
  pageKey: "campaigns",
  title: pageTitles.campaigns,
  subtitle: "Create, validate, launch, and control bulk outbound calling campaigns.",
});

scheduledAtInput.value = toLocalDateTimeInputValue();
setSchedulingDateDefaults();
toggleScheduledField();
resetPreview();
loadAgents();
loadCampaigns();
window.setInterval(loadCampaigns, frontendConfig.refreshIntervals.campaignsMs);
