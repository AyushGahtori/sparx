import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { showContentDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { callService } from "./services/callService.js";
import { escapeHtml, formatDateTime, formatDuration, formatStatusLabel } from "./utils/formatter.js";
import { showError, showSuccess } from "./utils/notifications.js";

const filtersForm = document.getElementById("recording-filters");
const clearFiltersButton = document.getElementById("clear-recording-filters-button");
const refreshButton = document.getElementById("refresh-recordings-button");
const messageRoot = document.getElementById("recording-message");
const tableBody = document.getElementById("recordings-table-body");

let allRecordings = [];
let activeAudioUrl = null;

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

function hasPlayableRecording(call) {
  return call.recording_status === "completed" && Boolean(call.recording_url);
}

function applyFilters(recordings) {
  const search = String(getFilterValue("search")).trim().toLowerCase();
  const recordingStatus = getFilterValue("recording_status");
  const callType = getFilterValue("call_type");

  return recordings.filter((call) => {
    if (recordingStatus && call.recording_status !== recordingStatus) {
      return false;
    }
    if (callType && call.call_type !== callType) {
      return false;
    }
    if (!search) {
      return true;
    }

    const haystack = [
      call.lead_name,
      call.phone,
      call.email,
      call.company,
      call.campaign_id,
      call.recording_sid,
      call.twilio_call_sid,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function renderRows(recordings) {
  if (!recordings.length) {
    renderTableEmpty(tableBody, 7, "No call recordings matched the current filters.");
    return;
  }

  tableBody.innerHTML = recordings
    .map(
      (call) => `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(call.lead_name)}</strong>
              <span class="table-subtext">${escapeHtml(call.phone)}</span>
            </div>
          </td>
          <td>${escapeHtml(call.call_type)}</td>
          <td><span class="status-pill ${escapeHtml(call.status)}">${escapeHtml(formatStatusLabel(call.status))}</span></td>
          <td><span class="status-pill ${escapeHtml(call.recording_status || "pending")}">${escapeHtml(formatStatusLabel(call.recording_status || "pending"))}</span></td>
          <td>${escapeHtml(formatDuration(call.recording_duration ?? call.duration, "-"))}</td>
          <td>${escapeHtml(formatDateTime(call.recording_available_at || call.ended_at || call.created_at))}</td>
          <td>
            <div class="table-actions">
              <button class="button secondary small" type="button" data-action="play" data-call-id="${escapeHtml(call.call_id)}" ${hasPlayableRecording(call) ? "" : "disabled"}>Play</button>
              <button class="button ghost small" type="button" data-action="details" data-call-id="${escapeHtml(call.call_id)}">Details</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function revokeActiveAudioUrl() {
  if (activeAudioUrl) {
    URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
  }
}

async function openPlayer(call) {
  clearMessage();
  revokeActiveAudioUrl();
  renderMessage("info", "Loading recording audio...");

  const blob = await callService.getRecordingAudio(call.call_id);
  activeAudioUrl = URL.createObjectURL(blob);
  clearMessage();

  showContentDialog({
    title: `${call.lead_name} recording`,
    bodyHtml: `
      <div class="detail-list">
        <div class="detail-row"><span class="detail-label">Phone</span><span>${escapeHtml(call.phone)}</span></div>
        <div class="detail-row"><span class="detail-label">Recording Status</span><span>${escapeHtml(formatStatusLabel(call.recording_status || "-"))}</span></div>
        <div class="detail-row"><span class="detail-label">Recording Duration</span><span>${escapeHtml(formatDuration(call.recording_duration ?? call.duration, "-"))}</span></div>
        <div class="detail-row"><span class="detail-label">Recording SID</span><span>${escapeHtml(call.recording_sid || "-")}</span></div>
      </div>
      <div style="margin-top: 1rem;">
        <audio controls preload="metadata" style="width: 100%;" src="${activeAudioUrl}"></audio>
      </div>
    `,
    footerHtml: `
      <a class="button secondary" href="${activeAudioUrl}" download="${escapeHtml(call.call_id)}.mp3">Download</a>
      <button class="button ghost" type="button" data-modal-close="true">Close</button>
    `,
  });
}

function openDetails(call) {
  showContentDialog({
    title: `${call.lead_name} recording details`,
    bodyHtml: `
      <div class="detail-list">
        <div class="detail-row"><span class="detail-label">Call ID</span><span>${escapeHtml(call.call_id)}</span></div>
        <div class="detail-row"><span class="detail-label">Twilio Call SID</span><span>${escapeHtml(call.twilio_call_sid || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Recording SID</span><span>${escapeHtml(call.recording_sid || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Source</span><span>${escapeHtml(call.recording_source || "-")}</span></div>
        <div class="detail-row"><span class="detail-label">Channels</span><span>${escapeHtml(String(call.recording_channels || "-"))}</span></div>
        <div class="detail-row"><span class="detail-label">Available At</span><span>${escapeHtml(formatDateTime(call.recording_available_at))}</span></div>
        <div class="detail-row"><span class="detail-label">Call Summary</span><span>${escapeHtml(call.summary || "No AI summary available yet.")}</span></div>
      </div>
    `,
    footerHtml: `<button class="button ghost" type="button" data-modal-close="true">Close</button>`,
  });
}

async function loadRecordings() {
  renderTableLoading(tableBody, 7, "Loading call recordings...");

  try {
    allRecordings = await callService.listRecordings();
    renderRows(applyFilters(allRecordings));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load call recordings.";
    renderTableError(tableBody, 7, message);
  }
}

async function handleAction(action, callId) {
  const call = allRecordings.find((item) => item.call_id === callId) || (await callService.getCall(callId));

  try {
    if (action === "play") {
      await openPlayer(call);
      return;
    }
    if (action === "details") {
      openDetails(call);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to complete the recording action.";
    renderMessage("error", message);
    showError(message);
  }
}

filtersForm.addEventListener("submit", (event) => {
  event.preventDefault();
  renderRows(applyFilters(allRecordings));
});

clearFiltersButton.addEventListener("click", () => {
  filtersForm.reset();
  renderRows(applyFilters(allRecordings));
});

refreshButton.addEventListener("click", async () => {
  await loadRecordings();
  showSuccess("Call recordings refreshed.");
});

tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) {
    return;
  }
  await handleAction(button.dataset.action, button.dataset.callId);
});

bootPage({
  pageKey: "call-recordings",
  title: pageTitles["call-recordings"],
  subtitle: "Play and inspect Twilio call recordings captured for outbound calls.",
});

loadRecordings();
window.setInterval(loadRecordings, frontendConfig.refreshIntervals.recordingsMs);
