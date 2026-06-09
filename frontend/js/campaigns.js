import { bootPage } from "./app.js";
import { pageTitles, frontendConfig } from "./config.js";
import { confirmDialog } from "./components/modal.js";
import { emptyState, errorState, loadingState } from "./components/loading.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { campaignService } from "./services/campaignService.js";
import { callService } from "./services/callService.js";
import {
  escapeHtml,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatStatusLabel,
  indiaDateTimeInputToIso,
  toLocalDateTimeInputValue,
  truncateText,
} from "./utils/formatter.js";
import { collectFormValues, normalizeOptionalString, requireFields } from "./utils/validation.js";
import { showError, showSuccess } from "./utils/notifications.js";

const form = document.getElementById("campaign-form");
const formMessage = document.getElementById("campaign-form-message");
const agentSelect = document.getElementById("agent-id");
const csvFileInput = document.getElementById("csv-file");
const previewPanel = document.getElementById("csv-preview-panel");
const createButton = document.getElementById("create-campaign-button");
const scheduleTypeSelect = document.getElementById("schedule-type");
const scheduledAtWrapper = document.getElementById("scheduled-at-wrapper");
const scheduledAtInput = document.getElementById("scheduled-at");
const dispatchModeInputs = Array.from(form.querySelectorAll('input[name="dispatch_mode"]'));
const filtersForm = document.getElementById("campaign-filters");
const clearFiltersButton = document.getElementById("clear-campaign-filters-button");
const tableBody = document.getElementById("campaign-table-body");
const refreshButton = document.getElementById("refresh-campaigns-button");
const refreshCampaignDataButton = document.getElementById("refresh-campaign-data-button");
const dashboardMessage = document.getElementById("campaign-dashboard-message");
const campaignDataPanel = document.getElementById("campaign-data-panel");

let previewContacts = [];
let previewLeadSource = null;
let allCampaigns = [];
let activeSearch = "";
let activeStatus = "";
let selectedCampaignId = "";

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
  createButton.textContent = isLoading ? "Creating Campaign..." : buildCreateButtonLabel();
}

function toggleScheduledField() {
  const isScheduled = scheduleTypeSelect.value === "scheduled";
  scheduledAtWrapper.classList.toggle("hidden", !isScheduled);
  scheduledAtInput.required = isScheduled;
  createButton.textContent = buildCreateButtonLabel();
}

function resetPreview() {
  previewContacts = [];
  previewLeadSource = null;
  previewPanel.innerHTML = emptyState("Upload a lead file to preview valid, invalid, and duplicate contacts.");
}

function getLifecycleStageMeta(stage) {
  const mapping = {
    new_lead: { label: "New Lead", className: "pending" },
    contacted: { label: "Contacted", className: "answered" },
    engaged: { label: "Engaged", className: "interested" },
    callback_scheduled: { label: "Callback Scheduled", className: "callback_requested" },
    meeting_scheduled: { label: "Meeting Scheduled", className: "meeting_requested" },
    client: { label: "Client", className: "completed" },
  };
  return mapping[stage] || { label: formatStatusLabel(stage, "Unknown"), className: "pending" };
}

function getSelectedDispatchMode() {
  return dispatchModeInputs.find((input) => input.checked)?.value || "parallel";
}

function formatDispatchModeLabel(mode) {
  return mode === "one_by_one" ? "One by one" : "All counted customers";
}

function formatDispatchModeSummary(mode) {
  return mode === "one_by_one" ? "1 active call at a time" : "Standard parallel queue";
}

function buildCreateButtonLabel() {
  if (scheduleTypeSelect.value === "scheduled") {
    return "Create Scheduled Campaign";
  }
  return getSelectedDispatchMode() === "one_by_one" ? "Create and Start 1-by-1" : "Create and Start Campaign";
}

function syncDispatchModeSelectionState() {
  dispatchModeInputs.forEach((input) => {
    input.closest(".choice-option")?.classList.toggle("is-selected", input.checked);
  });
  createButton.textContent = buildCreateButtonLabel();
}

function buildStagePill(stage) {
  const meta = getLifecycleStageMeta(stage);
  return `<span class="status-pill ${meta.className}">${escapeHtml(meta.label)}</span>`;
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
          <td>${escapeHtml(row.email || "-")}</td>
          <td>${escapeHtml(row.role || "-")}</td>
          <td>${escapeHtml(row.interest || "-")}</td>
          <td><span class="status-pill ${escapeHtml(row.validation_status)}">${escapeHtml(row.validation_status)}</span></td>
          <td>${escapeHtml(row.validation_message)}</td>
        </tr>
      `,
    )
    .join("");

  const sourceColumns = (preview.source_columns || []).length
    ? preview.source_columns.map((column) => `<code>${escapeHtml(column)}</code>`).join(" ")
    : "<span class='muted-text'>No structured columns detected</span>";
  const unmappedColumns = (preview.unmapped_columns || []).length
    ? preview.unmapped_columns.map((column) => `<code>${escapeHtml(column)}</code>`).join(" ")
    : "<span class='muted-text'>None</span>";

  return `
    <div class="campaign-source-meta">
      <span class="status-pill ready">${escapeHtml(preview.file_type)}</span>
      <span class="detail-text">${escapeHtml(preview.filename)}</span>
    </div>
    <div class="card-grid">
      <div class="stat-card"><span class="stat-label">Valid Contacts</span><span class="stat-value">${preview.valid_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Invalid Contacts</span><span class="stat-value">${preview.invalid_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Duplicate Contacts</span><span class="stat-value">${preview.duplicate_contacts}</span></div>
    </div>
    <div class="campaign-data-grid campaign-data-grid--compact">
      <div class="campaign-data-card">
        <span class="campaign-data-card__label">Detected Columns</span>
        <div class="campaign-code-line">${sourceColumns}</div>
      </div>
      <div class="campaign-data-card">
        <span class="campaign-data-card__label">Unmapped Columns</span>
        <div class="campaign-code-line">${unmappedColumns}</div>
      </div>
    </div>
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Phone</th>
            <th>Company</th>
            <th>Email</th>
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
  const dispatchMode = campaign.dispatch_mode || "parallel";
  const startLabel = dispatchMode === "one_by_one" ? "Start 1-by-1" : "Start";
  const resumeLabel = dispatchMode === "one_by_one" ? "Resume 1-by-1" : "Resume";

  if (["scheduled", "failed"].includes(campaign.status)) {
    buttons.push(`<button class="button secondary small" type="button" data-action="start" data-campaign-id="${campaign.campaign_id}">${startLabel}</button>`);
  }
  if (campaign.status === "running") {
    buttons.push(`<button class="button secondary small" type="button" data-action="pause" data-campaign-id="${campaign.campaign_id}">Pause</button>`);
    buttons.push(`<button class="button ghost small" type="button" data-action="stop" data-campaign-id="${campaign.campaign_id}">Stop</button>`);
  }
  if (campaign.status === "paused") {
    buttons.push(`<button class="button secondary small" type="button" data-action="resume" data-campaign-id="${campaign.campaign_id}">${resumeLabel}</button>`);
    buttons.push(`<button class="button ghost small" type="button" data-action="stop" data-campaign-id="${campaign.campaign_id}">Stop</button>`);
  }

  buttons.push(`<button class="button ghost small" type="button" data-action="data" data-campaign-id="${campaign.campaign_id}">Campaign Data</button>`);

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

    const productName = campaign.metadata?.product_brief?.product_name || "";
    const haystack = [
      campaign.campaign_name,
      campaign.campaign_type,
      campaign.call_objective,
      campaign.agent_name,
      productName,
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
    .map((campaign) => {
      const productName = campaign.metadata?.product_brief?.product_name || campaign.campaign_name;
      const dispatchMode = campaign.dispatch_mode || "parallel";
      return `
        <tr class="${selectedCampaignId === campaign.campaign_id ? "campaign-row--selected" : ""}">
          <td>
            <div class="table-title campaign-card-title">
              <strong>${escapeHtml(campaign.campaign_name)}</strong>
              <span class="table-subtext">${escapeHtml(campaign.campaign_type)} | ${escapeHtml(productName)} | ${escapeHtml(formatDispatchModeLabel(dispatchMode))}</span>
            </div>
          </td>
          <td><span class="status-pill ${escapeHtml(campaign.status)}">${escapeHtml(campaign.status)}</span></td>
          <td>
            <div class="progress-line">
              <span style="width: ${Math.min(100, Math.max(0, campaign.progress_percentage || 0))}%"></span>
            </div>
            <div>${campaign.completed_calls}/${campaign.total_contacts} completed</div>
            <div class="table-subtext">Pending: ${campaign.pending_calls} | Active: ${campaign.active_calls} | Retry: ${campaign.retry_calls} | ${escapeHtml(formatDispatchModeSummary(dispatchMode))}</div>
          </td>
          <td>${campaign.total_contacts}</td>
          <td>${formatPercent(campaign.success_rate)}</td>
          <td>${escapeHtml(formatDateTime(campaign.created_at))}</td>
          <td><div class="table-actions">${buildCampaignActions(campaign)}</div></td>
        </tr>
      `;
    })
    .join("");
}

async function loadAgents() {
  agentSelect.innerHTML = "<option>Loading agents...</option>";

  try {
    const agents = await callService.listAgents();
    if (!agents.length) {
      agentSelect.innerHTML = "<option value=''>No agents configured</option>";
      renderMessage(formMessage, "info", "No Deepgram agents are available.");
      return;
    }

    agentSelect.innerHTML = agents
      .map(
        (agent) => `
          <option value="${escapeHtml(agent.agent_id)}">
            ${escapeHtml(agent.agent_name)} - ${escapeHtml(agent.purpose)}
          </option>
        `,
      )
      .join("");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load agents.";
    renderMessage(formMessage, "error", message);
    agentSelect.innerHTML = "<option value=''>Unable to load agents</option>";
  }
}

async function previewLeadFile(file) {
  if (!file) {
    resetPreview();
    return;
  }

  previewPanel.innerHTML = loadingState("Validating lead file...");

  try {
    const preview = await campaignService.previewLeads(file);
    previewContacts = preview.contacts;
    previewLeadSource = {
      filename: preview.filename,
      file_type: preview.file_type,
      total_rows: preview.total_rows,
      invalid_contacts: preview.invalid_contacts,
      duplicate_contacts: preview.duplicate_contacts,
      source_columns: preview.source_columns || [],
      unmapped_columns: preview.unmapped_columns || [],
    };
    previewPanel.innerHTML = buildPreviewMarkup(preview);
    renderMessage(
      formMessage,
      "success",
      `${preview.valid_contacts} contacts are ready from ${preview.file_type.toUpperCase()} for ${formatDispatchModeLabel(getSelectedDispatchMode()).toLowerCase()} calling. ${preview.invalid_contacts} invalid and ${preview.duplicate_contacts} duplicate rows were detected.`,
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Lead preview failed.";
    previewContacts = [];
    previewLeadSource = null;
    previewPanel.innerHTML = errorState(message);
    renderMessage(formMessage, "error", message);
  }
}

function collectCampaignPayload() {
  const payload = collectFormValues(form);
  requireFields(payload, {
    campaign_name: "Campaign Name",
    agent_id: "Deepgram Agent",
    campaign_type: "Campaign Type",
    call_objective: "Call Objective",
    language: "Language",
    product_name: "Product Name",
    product_description: "Product Description",
  });

  if (!previewContacts.length || !previewLeadSource) {
    throw new Error("Upload and validate a lead file before creating the campaign.");
  }

  const campaignPayload = {
    campaign_name: payload.campaign_name,
    agent_id: payload.agent_id,
    campaign_type: payload.campaign_type,
    call_objective: payload.call_objective,
    language: payload.language,
    priority: payload.priority,
    schedule_type: payload.schedule_type,
    dispatch_mode: payload.dispatch_mode || "parallel",
    notes: normalizeOptionalString(payload.notes),
    contacts: previewContacts,
    lead_source: previewLeadSource,
    product_brief: {
      product_name: payload.product_name,
      product_description: payload.product_description,
      product_website: normalizeOptionalString(payload.product_website),
      offer_summary: normalizeOptionalString(payload.offer_summary),
      value_proposition: normalizeOptionalString(payload.value_proposition),
      target_audience: normalizeOptionalString(payload.target_audience),
      qualification_criteria: normalizeOptionalString(payload.qualification_criteria),
      objection_handling: normalizeOptionalString(payload.objection_handling),
      meeting_goal: normalizeOptionalString(payload.meeting_goal),
    },
  };

  if (campaignPayload.schedule_type === "scheduled") {
    if (!payload.scheduled_at) {
      throw new Error("Please select a scheduled date and time.");
    }
    campaignPayload.scheduled_at = indiaDateTimeInputToIso(payload.scheduled_at);
  }

  return campaignPayload;
}

async function loadCampaigns() {
  renderTableLoading(tableBody, 7, "Loading campaigns...");

  try {
    allCampaigns = await campaignService.listCampaigns();
    renderCampaignRows(applyFilters(allCampaigns));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load campaigns.";
    renderTableError(tableBody, 7, message);
  }
}

function buildDataCards(metrics, campaign) {
  return `
    <div class="card-grid">
      <div class="stat-card"><span class="stat-label">Contacts</span><span class="stat-value">${metrics.total_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Reached</span><span class="stat-value">${metrics.reached_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Interested</span><span class="stat-value">${metrics.interested_contacts}</span></div>
      <div class="stat-card"><span class="stat-label">Callbacks</span><span class="stat-value">${metrics.callbacks_scheduled}</span></div>
      <div class="stat-card"><span class="stat-label">Meetings Pending</span><span class="stat-value">${metrics.meetings_pending}</span></div>
      <div class="stat-card"><span class="stat-label">Clients</span><span class="stat-value">${metrics.converted_clients}</span></div>
      <div class="stat-card"><span class="stat-label">Success Rate</span><span class="stat-value">${formatPercent(campaign.success_rate)}</span></div>
      <div class="stat-card"><span class="stat-label">Answered Calls</span><span class="stat-value">${campaign.answered_calls}</span></div>
    </div>
  `;
}

function buildOverviewCards(data) {
  const productBrief = data.product_brief || {};
  const leadSource = data.lead_source || {};
  return `
    <div class="campaign-data-grid">
      <article class="campaign-data-card">
        <span class="campaign-data-card__label">Campaign & Product</span>
        <h3>${escapeHtml(data.campaign.campaign_name)}</h3>
        <p class="campaign-data-card__text">${escapeHtml(productBrief.product_description || data.campaign.call_objective)}</p>
        <div class="key-value-grid">
          <div><strong>Product:</strong> ${escapeHtml(productBrief.product_name || data.campaign.campaign_name)}</div>
          <div><strong>Website:</strong> ${escapeHtml(productBrief.product_website || "Not provided")}</div>
          <div><strong>Offer:</strong> ${escapeHtml(productBrief.offer_summary || "Not provided")}</div>
          <div><strong>Target Audience:</strong> ${escapeHtml(productBrief.target_audience || "Not provided")}</div>
          <div><strong>Qualification:</strong> ${escapeHtml(productBrief.qualification_criteria || "Not provided")}</div>
          <div><strong>Meeting Goal:</strong> ${escapeHtml(productBrief.meeting_goal || data.campaign.call_objective)}</div>
          <div><strong>Objection Handling:</strong> ${escapeHtml(productBrief.objection_handling || "Not provided")}</div>
          <div><strong>Operator Notes:</strong> ${escapeHtml(data.campaign.notes || "None")}</div>
        </div>
      </article>
      <article class="campaign-data-card">
        <span class="campaign-data-card__label">Lead Source & Execution</span>
        <div class="key-value-grid">
          <div><strong>Source File:</strong> ${escapeHtml(leadSource.filename || "Manual/Unknown")}</div>
          <div><strong>File Type:</strong> ${escapeHtml(leadSource.file_type || "Unknown")}</div>
          <div><strong>Total Rows:</strong> ${escapeHtml(String(leadSource.total_rows ?? data.campaign.total_contacts))}</div>
          <div><strong>Invalid Rows:</strong> ${escapeHtml(String(leadSource.invalid_contacts ?? 0))}</div>
          <div><strong>Duplicate Rows:</strong> ${escapeHtml(String(leadSource.duplicate_contacts ?? 0))}</div>
          <div><strong>Priority:</strong> ${escapeHtml(data.campaign.priority)}</div>
          <div><strong>Dispatch Mode:</strong> ${escapeHtml(formatDispatchModeLabel(data.campaign.dispatch_mode || "parallel"))}</div>
          <div><strong>Status:</strong> ${escapeHtml(data.campaign.status)}</div>
          <div><strong>Scheduled At:</strong> ${escapeHtml(formatDateTime(data.campaign.scheduled_at))}</div>
          <div><strong>Started At:</strong> ${escapeHtml(formatDateTime(data.campaign.started_at))}</div>
          <div><strong>Completed At:</strong> ${escapeHtml(formatDateTime(data.campaign.completed_at))}</div>
        </div>
        <div class="campaign-code-line">
          ${(leadSource.source_columns || []).length
            ? leadSource.source_columns.map((column) => `<code>${escapeHtml(column)}</code>`).join(" ")
            : "<span class='muted-text'>No structured source columns stored</span>"}
        </div>
      </article>
    </div>
  `;
}

function buildContactsTable(contacts) {
  if (!contacts.length) {
    return emptyState("No contacts were stored for this campaign.");
  }

  return `
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>Lead</th>
            <th>Company</th>
            <th>Phone</th>
            <th>Email</th>
            <th>Pipeline Stage</th>
            <th>Status</th>
            <th>Next Action</th>
            <th>Last Activity</th>
          </tr>
        </thead>
        <tbody>
          ${contacts
            .map(
              (contact) => `
                <tr>
                  <td>
                    <div class="table-title">
                      <strong>${escapeHtml(contact.name)}</strong>
                      <span class="table-subtext">${escapeHtml(contact.role || "Role not provided")}</span>
                    </div>
                  </td>
                  <td>${escapeHtml(contact.company || "-")}</td>
                  <td>${escapeHtml(contact.phone)}</td>
                  <td>${escapeHtml(contact.email || "-")}</td>
                  <td>${buildStagePill(contact.lifecycle_stage)}</td>
                  <td><span class="status-pill ${escapeHtml(contact.status)}">${escapeHtml(formatStatusLabel(contact.status))}</span></td>
                  <td>${escapeHtml(truncateText(contact.latest_next_action || contact.latest_summary || contact.notes || "-", 80, "-"))}</td>
                  <td>${escapeHtml(formatDateTime(contact.last_activity_at))}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function buildMeetingsTable(meetings) {
  if (!meetings.length) {
    return emptyState("No meeting-related outcomes have been documented for this campaign yet.");
  }

  return `
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>Lead</th>
            <th>Company</th>
            <th>Meeting Time</th>
            <th>Scheduled For</th>
            <th>Status</th>
            <th>Stage</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          ${meetings
            .map(
              (meeting) => `
                <tr>
                  <td>${escapeHtml(meeting.lead_name)}</td>
                  <td>${escapeHtml(meeting.company || "-")}</td>
                  <td>${escapeHtml(meeting.meeting_time || "-")}</td>
                  <td>${escapeHtml(formatDateTime(meeting.scheduled_for))}</td>
                  <td><span class="status-pill ${escapeHtml(meeting.status)}">${escapeHtml(formatStatusLabel(meeting.status))}</span></td>
                  <td>${buildStagePill(meeting.lifecycle_stage)}</td>
                  <td>${escapeHtml(truncateText(meeting.summary || meeting.next_action || "-", 90, "-"))}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function buildCallbacksTable(callbacks) {
  if (!callbacks.length) {
    return emptyState("No callbacks are linked to this campaign.");
  }

  return `
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>Lead</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Callback Reason</th>
            <th>Requested Time</th>
            <th>Scheduled For</th>
            <th>Retries</th>
          </tr>
        </thead>
        <tbody>
          ${callbacks
            .map(
              (callback) => `
                <tr>
                  <td>${escapeHtml(callback.lead_name)}</td>
                  <td><span class="status-pill ${escapeHtml(callback.status)}">${escapeHtml(formatStatusLabel(callback.status))}</span></td>
                  <td><span class="status-pill ${escapeHtml(callback.priority)}">${escapeHtml(callback.priority)}</span></td>
                  <td>${escapeHtml(truncateText(callback.callback_reason, 90, "-"))}</td>
                  <td>${escapeHtml(callback.requested_time_raw)}</td>
                  <td>${escapeHtml(formatDateTime(callback.normalized_callback_time))}</td>
                  <td>${escapeHtml(String(callback.retry_count))}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function buildTranscriptLines(entries) {
  if (!entries.length) {
    return "<p class='muted-text'>Transcript not available yet.</p>";
  }

  return `
    <div class="transcript-list">
      ${entries
        .map(
          (entry) => `
            <div class="transcript-entry">
              <div class="transcript-meta">
                <strong class="transcript-speaker">${escapeHtml(entry.speaker)}</strong>
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

function buildEventList(events) {
  if (!events.length) {
    return "<p class='muted-text'>No event log available yet.</p>";
  }
  return `
    <div class="campaign-inline-list">
      ${events
        .map(
          (event) => `
            <div class="campaign-inline-list__item">
              <strong>${escapeHtml(formatStatusLabel(event.event_type))}</strong>
              <span>${escapeHtml(event.message || "-")}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function buildConversationCards(calls) {
  if (!calls.length) {
    return emptyState("Calls will appear here after the campaign starts dialing.");
  }

  return `
    <div class="campaign-call-stack">
      ${calls
        .slice(0, 10)
        .map(
          (call) => `
            <details class="campaign-call-card">
              <summary>
                <div>
                  <strong>${escapeHtml(call.lead_name)}</strong>
                  <div class="table-subtext">${escapeHtml(call.company || "-")} | ${escapeHtml(call.phone)}</div>
                </div>
                <div class="campaign-call-card__summary">
                  <span class="status-pill ${escapeHtml(call.status)}">${escapeHtml(formatStatusLabel(call.status))}</span>
                  <span>${escapeHtml(formatDuration(call.duration, "-"))}</span>
                </div>
              </summary>
              <div class="campaign-call-card__body">
                <div class="key-value-grid">
                  <div><strong>Outcome:</strong> ${escapeHtml(formatStatusLabel(call.call_outcome || call.status))}</div>
                  <div><strong>Lead Type:</strong> ${escapeHtml(formatStatusLabel(call.lead_type || "-"))}</div>
                  <div><strong>Meeting Time:</strong> ${escapeHtml(call.meeting_time || "-")}</div>
                  <div><strong>Next Action:</strong> ${escapeHtml(call.next_action || "-")}</div>
                  <div><strong>Summary:</strong> ${escapeHtml(call.summary || "-")}</div>
                  <div><strong>Notes:</strong> ${escapeHtml(call.short_notes || "-")}</div>
                </div>
                <h4>Transcript Excerpt</h4>
                ${buildTranscriptLines(call.transcript_excerpt || [])}
                <h4>Event Log</h4>
                ${buildEventList(call.event_log || [])}
              </div>
            </details>
          `,
        )
        .join("")}
    </div>
  `;
}

function buildTimelineTable(timeline) {
  if (!timeline.length) {
    return emptyState("The campaign timeline will fill as calls, callbacks, and follow-ups are recorded.");
  }

  return `
    <div class="table-shell compact">
      <table class="data-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Source</th>
            <th>Event</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          ${timeline
            .slice(0, 40)
            .map(
              (event) => `
                <tr>
                  <td>${escapeHtml(formatDateTime(event.timestamp))}</td>
                  <td>${escapeHtml(formatStatusLabel(event.source_type))}</td>
                  <td>${escapeHtml(formatStatusLabel(event.event_type))}</td>
                  <td>${escapeHtml(truncateText(event.message, 120, "-"))}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function buildCampaignDataMarkup(data) {
  const productName = data.product_brief?.product_name || data.campaign.campaign_name;
  return `
    <div class="campaign-data-shell">
      <div class="campaign-data-hero">
        <div>
          <span class="eyebrow">Selected Campaign</span>
          <h3>${escapeHtml(data.campaign.campaign_name)}</h3>
          <p>${escapeHtml(data.product_brief?.value_proposition || data.campaign.call_objective)}</p>
        </div>
        <div class="campaign-data-hero__meta">
          <span class="status-pill ${escapeHtml(data.campaign.status)}">${escapeHtml(data.campaign.status)}</span>
          <span class="campaign-data-hero__product">${escapeHtml(productName)}</span>
        </div>
      </div>

      ${buildDataCards(data.metrics, data.campaign)}
      ${buildOverviewCards(data)}

      <section class="campaign-data-section">
        <div class="panel-header">
          <div>
            <h3>Lead Pipeline</h3>
            <p class="panel-subtitle">Every extracted lead with current call stage and next action.</p>
          </div>
        </div>
        ${buildContactsTable(data.contacts || [])}
      </section>

      <section class="campaign-data-section">
        <div class="panel-header">
          <div>
            <h3>Meetings</h3>
            <p class="panel-subtitle">Meeting requests, scheduled follow-ups, and confirmed client conversations.</p>
          </div>
        </div>
        ${buildMeetingsTable(data.meetings || [])}
      </section>

      <section class="campaign-data-section">
        <div class="panel-header">
          <div>
            <h3>Callbacks</h3>
            <p class="panel-subtitle">Automatic and manual follow-ups linked back to the campaign.</p>
          </div>
        </div>
        ${buildCallbacksTable(data.callbacks || [])}
      </section>

      <section class="campaign-data-section">
        <div class="panel-header">
          <div>
            <h3>Conversations</h3>
            <p class="panel-subtitle">Documented call summaries, transcript excerpts, and event history.</p>
          </div>
        </div>
        ${buildConversationCards(data.calls || [])}
      </section>

      <section class="campaign-data-section">
        <div class="panel-header">
          <div>
            <h3>Timeline</h3>
            <p class="panel-subtitle">Merged operational history from campaign, contacts, calls, and callbacks.</p>
          </div>
        </div>
        ${buildTimelineTable(data.timeline || [])}
      </section>
    </div>
  `;
}

async function loadCampaignData(campaignId, options = {}) {
  const { scrollIntoView = true, silent = false } = options;
  selectedCampaignId = campaignId;
  campaignDataPanel.innerHTML = loadingState("Loading campaign intelligence...");

  try {
    const data = await campaignService.getCampaignData(campaignId);
    campaignDataPanel.innerHTML = buildCampaignDataMarkup(data);
    renderCampaignRows(applyFilters(allCampaigns));
    if (scrollIntoView) {
      campaignDataPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (!silent) {
      showSuccess(`Loaded campaign data for ${data.campaign.campaign_name}.`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load campaign data.";
    campaignDataPanel.innerHTML = errorState(message);
    renderMessage(dashboardMessage, "error", message);
    showError(message);
  }
}

async function handleCampaignAction(action, campaignId) {
  clearMessage(dashboardMessage);

  try {
    if (action === "data") {
      await loadCampaignData(campaignId);
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
      if (selectedCampaignId === campaignId) {
        selectedCampaignId = "";
        campaignDataPanel.innerHTML = emptyState("Select “Campaign Data” on a campaign row to load the production campaign workspace.");
      }
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
    if (selectedCampaignId) {
      await loadCampaignData(selectedCampaignId, { scrollIntoView: false, silent: true });
    }
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
    toggleScheduledField();
    resetPreview();
    await loadCampaigns();
    await loadCampaignData(campaign.campaign_id, { scrollIntoView: true, silent: true });
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
    toggleScheduledField();
    syncDispatchModeSelectionState();
  }, 0);
  resetPreview();
});

csvFileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files || [];
  await previewLeadFile(file);
});

scheduleTypeSelect.addEventListener("change", toggleScheduledField);
dispatchModeInputs.forEach((input) => {
  input.addEventListener("change", () => {
    syncDispatchModeSelectionState();
    if (previewContacts.length) {
      renderMessage(
        formMessage,
        "info",
        `${previewContacts.length} validated contacts are ready for ${formatDispatchModeLabel(getSelectedDispatchMode()).toLowerCase()} calling.`,
      );
    }
  });
});

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

refreshCampaignDataButton.addEventListener("click", async () => {
  if (!selectedCampaignId) {
    showError("Select a campaign first to refresh campaign data.");
    return;
  }
  await loadCampaignData(selectedCampaignId, { scrollIntoView: false, silent: true });
  showSuccess("Campaign data refreshed.");
});

bootPage({
  pageKey: "campaigns",
  title: pageTitles.campaigns,
  subtitle: "Create, validate, launch, and monitor outbound calling campaigns with full campaign intelligence.",
});

scheduledAtInput.value = toLocalDateTimeInputValue();
toggleScheduledField();
syncDispatchModeSelectionState();
resetPreview();
loadAgents();
loadCampaigns();
window.setInterval(async () => {
  await loadCampaigns();
  if (selectedCampaignId) {
    await loadCampaignData(selectedCampaignId, { scrollIntoView: false, silent: true });
  }
}, frontendConfig.refreshIntervals.campaignsMs);
