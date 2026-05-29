import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { callService } from "./services/callService.js";
import { getSearchParam } from "./router.js";
import {
  escapeHtml,
  formatDateTime,
  formatStatusLabel,
} from "./utils/formatter.js";
import { collectFormValues, requireFields, validatePhoneE164 } from "./utils/validation.js";
import { showError, showInfo, showSuccess } from "./utils/notifications.js";

const form = document.getElementById("manual-call-form");
const formMessage = document.getElementById("form-message");
const statusPanel = document.getElementById("call-status-panel");
const submitButton = document.getElementById("submit-button");
const agentSelect = document.getElementById("agent-id");

let activeCallId = null;
let pollTimer = null;

function renderMessage(type, message) {
  formMessage.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

function clearMessage() {
  formMessage.innerHTML = "";
}

function setLoadingState(isLoading) {
  submitButton.disabled = isLoading;
  submitButton.textContent = isLoading ? "Starting AI Call..." : "Start AI Call";
}

function buildStatusMarkup(call) {
  const retryTime = call.next_retry_time ? formatDateTime(call.next_retry_time) : "Not scheduled";
  const startedAt = call.started_at ? formatDateTime(call.started_at) : "Not started";
  const endedAt = call.ended_at ? formatDateTime(call.ended_at) : "In progress";
  const summary = call.summary || call.ai_error || "Post-call intelligence is not available yet.";

  return `
    <div class="detail-list">
      <div class="detail-row">
        <span class="detail-label">Status</span>
        <span><span class="status-pill ${escapeHtml(call.status)}">${escapeHtml(formatStatusLabel(call.status))}</span></span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Call ID</span>
        <span>${escapeHtml(call.call_id)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Lead</span>
        <span>${escapeHtml(call.lead_name)} (${escapeHtml(call.phone)})</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Agent</span>
        <span>${escapeHtml(call.agent_name)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Twilio Call SID</span>
        <span>${escapeHtml(call.twilio_call_sid || "Pending")}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Started At</span>
        <span>${escapeHtml(startedAt)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Ended At</span>
        <span>${escapeHtml(endedAt)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Retry Plan</span>
        <span>Retry Count: ${call.retry_count} | Next Retry: ${escapeHtml(retryTime)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Meeting / Callback</span>
        <span>Meeting Requested: ${call.meeting_requested ? "Yes" : "No"} | Callback Requested: ${call.callback_requested ? "Yes" : "No"}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">AI Processing</span>
        <span>${escapeHtml(formatStatusLabel(call.ai_processing_status || "not_started"))}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">AI Summary</span>
        <span>${escapeHtml(summary)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Next Action</span>
        <span>${escapeHtml(call.next_action || "No recommendation available yet.")}</span>
      </div>
    </div>
  `;
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function refreshCallStatus() {
  if (!activeCallId) {
    return;
  }

  try {
    const call = await callService.getCall(activeCallId);
    statusPanel.innerHTML = buildStatusMarkup(call);

    const finalStatuses = ["completed", "failed", "busy", "no_answer", "meeting_requested", "callback_requested"];
    const finalAiStatuses = ["completed", "failed", "skipped", "not_started"];
    if (finalStatuses.includes(call.status) && finalAiStatuses.includes(call.ai_processing_status)) {
      stopPolling();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to refresh call status.";
    renderMessage("error", message);
    showError(message);
    stopPolling();
  }
}

function startPolling(callId) {
  stopPolling();
  activeCallId = callId;
  pollTimer = window.setInterval(refreshCallStatus, frontendConfig.refreshIntervals.manualCallMs);
}

function validatePayload(payload) {
  requireFields(payload, {
    lead_name: "Lead Name",
    phone: "Phone Number",
    agent_id: "Deepgram Agent",
    call_objective: "Call Objective",
    language: "Language",
  });

  if (!validatePhoneE164(payload.phone)) {
    throw new Error("Phone number must be in E.164 format, for example +919999999999.");
  }
}

async function loadAgents() {
  agentSelect.innerHTML = "<option>Loading agents...</option>";

  try {
    const agents = await callService.listAgents();
    if (!agents.length) {
      agentSelect.innerHTML = "<option value=''>No agents configured</option>";
      renderMessage("info", "No Deepgram agents are configured yet.");
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

    const requestedAgentId = getSearchParam("agent_id");
    if (requestedAgentId) {
      agentSelect.value = requestedAgentId;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load agents.";
    agentSelect.innerHTML = "<option value=''>Unable to load agents</option>";
    renderMessage("error", message);
  }
}

function applyPrefillFromQuery() {
  const fieldNames = [
    "lead_name",
    "phone",
    "company",
    "city",
    "role",
    "interest",
    "call_objective",
    "additional_context",
    "language",
    "priority",
  ];

  let applied = false;
  fieldNames.forEach((fieldName) => {
    const value = getSearchParam(fieldName);
    if (!value) {
      return;
    }

    const field = form.elements.namedItem(fieldName);
    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) {
      field.value = value;
      applied = true;
    }
  });

  if (applied) {
    showInfo("Lead details were prefilled from call history for a retry.");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();
  setLoadingState(true);

  try {
    const payload = collectFormValues(form);
    validatePayload(payload);
    const call = await callService.startIndividualCall(payload);
    activeCallId = call.call_id;
    statusPanel.innerHTML = buildStatusMarkup(call);
    renderMessage("success", `Call ${call.call_id} was created and sent to Twilio.`);
    showSuccess("Manual call started successfully.");
    startPolling(call.call_id);
    await refreshCallStatus();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to start the call.";
    renderMessage("error", message);
    showError(message);
  } finally {
    setLoadingState(false);
  }
});

form.addEventListener("reset", () => {
  clearMessage();
  stopPolling();
  activeCallId = null;
  statusPanel.innerHTML = `<div class="empty-state">No call has been started yet.</div>`;
});

bootPage({
  pageKey: "manual-call",
  title: pageTitles["manual-call"],
  subtitle: "Start a live outbound AI call and monitor its lifecycle.",
});

applyPrefillFromQuery();
loadAgents();
