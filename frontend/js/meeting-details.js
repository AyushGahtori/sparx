import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { confirmDialog, showContentDialog } from "./components/modal.js";
import { renderTableEmpty, renderTableError, renderTableLoading } from "./components/table.js";
import { meetingService } from "./services/meetingService.js";
import {
  escapeHtml,
  formatDateTime,
  formatStatusLabel,
  indiaDateTimeInputToIso,
  isAfterNowInIndia,
  parseAppDate,
  toLocalDateTimeInputValue,
  truncateText,
} from "./utils/formatter.js";
import { toIsoRangeEnd, toIsoRangeStart } from "./utils/validation.js";
import { showError, showSuccess } from "./utils/notifications.js";

const meetingSummaryPanel = document.getElementById("meeting-summary-panel");
const meetingFiltersForm = document.getElementById("meeting-filters");
const meetingDashboardMessage = document.getElementById("meeting-dashboard-message");
const meetingTableBody = document.getElementById("meeting-table-body");
const refreshMeetingsButton = document.getElementById("refresh-meetings-button");
const syncMeetingsButton = document.getElementById("sync-meetings-button");
const clearMeetingFiltersButton = document.getElementById("clear-meeting-filters-button");

let allMeetings = [];

function getFilterValue(fieldName) {
  const field = meetingFiltersForm.elements.namedItem(fieldName);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
    return field.value || "";
  }
  return "";
}

function renderMessage(type, message) {
  meetingDashboardMessage.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

function clearMessage() {
  meetingDashboardMessage.innerHTML = "";
}

function buildServerFilters() {
  return {
    status: getFilterValue("status") || undefined,
    date_from: toIsoRangeStart(getFilterValue("date_from")),
    date_to: toIsoRangeEnd(getFilterValue("date_to")),
  };
}

function applyClientFilters(meetings) {
  const search = String(getFilterValue("search")).trim().toLowerCase();
  if (!search) {
    return meetings;
  }
  return meetings.filter((meeting) => {
    const haystack = [
      meeting.title,
      meeting.attendee_email,
      ...(meeting.attendees || []),
      meeting.meet_link,
      meeting.event_link,
      meeting.description,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function renderSummary(meetings) {
  const confirmed = meetings.filter((meeting) => meeting.status === "confirmed").length;
  const upcoming = meetings.filter((meeting) => isAfterNowInIndia(meeting.scheduled_for)).length;
  const canceled = meetings.filter((meeting) => meeting.status === "canceled").length;
  const completed = meetings.filter((meeting) => meeting.status === "completed").length;
  const withMeetLinks = meetings.filter((meeting) => meeting.meet_link).length;

  meetingSummaryPanel.innerHTML = `
    <div class="card-grid">
      <div class="stat-card"><span class="stat-label">Upcoming</span><span class="stat-value">${upcoming}</span></div>
      <div class="stat-card"><span class="stat-label">Confirmed</span><span class="stat-value">${confirmed}</span></div>
      <div class="stat-card"><span class="stat-label">Meeting Done</span><span class="stat-value">${completed}</span></div>
      <div class="stat-card"><span class="stat-label">Meet Links</span><span class="stat-value">${withMeetLinks}</span></div>
      <div class="stat-card"><span class="stat-label">Canceled</span><span class="stat-value">${canceled}</span></div>
    </div>
  `;
}

function renderMeetingTable(meetings) {
  if (!meetings.length) {
    renderTableEmpty(meetingTableBody, 6, "No Google Meet records matched the current filters.");
    return;
  }

  meetingTableBody.innerHTML = meetings
    .map((meeting) => {
      const attendees = meeting.attendees?.length ? meeting.attendees.join(", ") : meeting.attendee_email || "-";
      return `
        <tr>
          <td>
            <div class="table-title">
              <strong>${escapeHtml(meeting.title)}</strong>
              <span class="table-subtext">${escapeHtml(truncateText(meeting.description, 90, "No description"))}</span>
            </div>
          </td>
          <td>
            <div>${escapeHtml(formatDateTime(meeting.scheduled_for))}</div>
            <div class="table-subtext">Ends ${escapeHtml(formatDateTime(meeting.ends_at, "-"))}</div>
          </td>
          <td>${escapeHtml(attendees)}</td>
          <td>
            <div class="table-actions">
              ${meeting.meet_link ? `<a class="button secondary small" href="${escapeHtml(meeting.meet_link)}" target="_blank" rel="noopener">Meet</a>` : ""}
              ${meeting.event_link ? `<a class="button ghost small" href="${escapeHtml(meeting.event_link)}" target="_blank" rel="noopener">Calendar</a>` : ""}
            </div>
          </td>
          <td><span class="status-pill ${escapeHtml(meeting.status)}">${escapeHtml(formatStatusLabel(meeting.status))}</span></td>
          <td>
            <div class="table-actions">
              ${
                !["completed", "canceled"].includes(meeting.status)
                  ? `
                    <button class="button secondary small" type="button" data-action="done" data-meeting-id="${escapeHtml(meeting.meeting_id)}">Mark Done</button>
                    <button class="button ghost small" type="button" data-action="reschedule" data-meeting-id="${escapeHtml(meeting.meeting_id)}">Reschedule</button>
                    <button class="button ghost small danger-outline" type="button" data-action="cancel" data-meeting-id="${escapeHtml(meeting.meeting_id)}">Cancel</button>
                  `
                  : ""
              }
              <button class="button ghost small danger-outline" type="button" data-action="delete" data-meeting-id="${escapeHtml(meeting.meeting_id)}">Delete</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function loadMeetings({ syncGoogle = true } = {}) {
  renderTableLoading(meetingTableBody, 6, "Loading Google Meet records...");

  try {
    allMeetings = await meetingService.listMeetings({ ...buildServerFilters(), sync_google: syncGoogle });
    const filteredMeetings = applyClientFilters(allMeetings);
    renderMeetingTable(filteredMeetings);
    renderSummary(filteredMeetings);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load meeting details.";
    renderTableError(meetingTableBody, 6, message);
    meetingSummaryPanel.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
  }
}

function openRescheduleDialog(meeting) {
  return new Promise((resolve) => {
    const defaultStart = toLocalDateTimeInputValue(meeting.scheduled_for || new Date());
    const defaultEnd = toLocalDateTimeInputValue(meeting.ends_at || new Date(parseAppDate(meeting.scheduled_for).getTime() + 30 * 60000));
    const dialog = showContentDialog({
      title: "Reschedule meeting",
      bodyHtml: `
        <div class="form-grid">
          <div class="form-field full-width">
            <label for="meeting-start-input">Start Date and Time</label>
            <input id="meeting-start-input" type="datetime-local" value="${escapeHtml(defaultStart)}" required>
          </div>
          <div class="form-field full-width">
            <label for="meeting-end-input">End Date and Time</label>
            <input id="meeting-end-input" type="datetime-local" value="${escapeHtml(defaultEnd)}">
          </div>
        </div>
      `,
      footerHtml: `
        <button class="button ghost" type="button" data-reschedule-action="cancel">Cancel</button>
        <button class="button primary" type="button" data-reschedule-action="save">Reschedule</button>
      `,
    });
    const root = document.getElementById("modal-root");
    const startInput = root?.querySelector("#meeting-start-input");
    const endInput = root?.querySelector("#meeting-end-input");
    startInput?.focus();

    const handleClick = (event) => {
      const action = event.target instanceof HTMLElement ? event.target.dataset.rescheduleAction : null;
      if (!action) {
        return;
      }
      root.removeEventListener("click", handleClick);
      if (action === "cancel") {
        dialog.close();
        resolve(null);
        return;
      }
      const scheduledFor = startInput instanceof HTMLInputElement ? startInput.value : "";
      const endsAt = endInput instanceof HTMLInputElement ? endInput.value : "";
      dialog.close();
      resolve({
        scheduled_for: scheduledFor ? indiaDateTimeInputToIso(scheduledFor) : null,
        ends_at: endsAt ? indiaDateTimeInputToIso(endsAt) : null,
      });
    };

    root.addEventListener("click", handleClick);
  });
}

function openCancelDialog() {
  return new Promise((resolve) => {
    const dialog = showContentDialog({
      title: "Cancel meeting",
      bodyHtml: `
        <div class="form-grid">
          <div class="form-field full-width">
            <label for="meeting-cancel-reason">Cancellation Reason</label>
            <textarea id="meeting-cancel-reason" rows="4" maxlength="1000" placeholder="Why is this meeting being cancelled?" required></textarea>
          </div>
          <p class="muted-text full-width">This removes the Calendar event and schedules one follow-up call 10 minutes from now to ask about rescheduling.</p>
        </div>
      `,
      footerHtml: `
        <button class="button ghost" type="button" data-cancel-action="close">Close</button>
        <button class="button danger" type="button" data-cancel-action="save">Cancel Meeting</button>
      `,
    });
    const root = document.getElementById("modal-root");
    const reasonInput = root?.querySelector("#meeting-cancel-reason");
    reasonInput?.focus();

    const handleClick = (event) => {
      const action = event.target instanceof HTMLElement ? event.target.dataset.cancelAction : null;
      if (!action) {
        return;
      }
      if (action === "close") {
        root.removeEventListener("click", handleClick);
        dialog.close();
        resolve(null);
        return;
      }
      const reason = reasonInput instanceof HTMLTextAreaElement ? reasonInput.value.trim() : "";
      if (reason.length < 3) {
        showError("Please enter a cancellation reason.");
        reasonInput?.focus();
        return;
      }
      root.removeEventListener("click", handleClick);
      dialog.close();
      resolve({ reason });
    };

    root.addEventListener("click", handleClick);
  });
}

async function handleMeetingAction(action, meetingId) {
  clearMessage();
  const meeting = allMeetings.find((item) => item.meeting_id === meetingId);

  try {
    if (action === "reschedule") {
      const payload = await openRescheduleDialog(meeting || {});
      if (!payload?.scheduled_for) {
        return;
      }
      await meetingService.rescheduleMeeting(meetingId, payload);
      renderMessage("success", "Meeting rescheduled successfully.");
      showSuccess("Meeting rescheduled.");
    } else if (action === "done") {
      const confirmed = await confirmDialog({
        title: "Mark meeting done",
        message: "This will mark the meeting completed in the database and remove the event from Google Calendar.",
        confirmLabel: "Mark done",
      });
      if (!confirmed) {
        return;
      }
      await meetingService.markMeetingDone(meetingId);
      renderMessage("success", "Meeting marked done and removed from Google Calendar.");
      showSuccess("Meeting marked done.");
    } else if (action === "cancel") {
      const payload = await openCancelDialog();
      if (!payload) {
        return;
      }
      const result = await meetingService.cancelMeeting(meetingId, payload);
      const suffix = result?.callback_id ? " A one-time callback was scheduled for 10 minutes from now." : "";
      renderMessage("success", `Meeting cancelled and removed from Google Calendar.${suffix}`);
      showSuccess("Meeting cancelled.");
    } else if (action === "delete") {
      const confirmed = await confirmDialog({
        title: "Delete meeting",
        message: "This will delete the Google Calendar event and remove the meeting record from the database.",
        confirmLabel: "Delete meeting",
        confirmVariant: "danger",
      });
      if (!confirmed) {
        return;
      }
      await meetingService.deleteMeeting(meetingId);
      renderMessage("success", "Meeting deleted successfully.");
      showSuccess("Meeting deleted.");
    }
    await loadMeetings({ syncGoogle: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to update the meeting.";
    renderMessage("error", message);
    showError(message);
  }
}

meetingFiltersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadMeetings();
});

clearMeetingFiltersButton.addEventListener("click", async () => {
  meetingFiltersForm.reset();
  await loadMeetings();
});

refreshMeetingsButton.addEventListener("click", async () => {
  await loadMeetings();
  showSuccess("Meeting details refreshed.");
});

syncMeetingsButton.addEventListener("click", async () => {
  clearMessage();
  try {
    const result = await meetingService.syncMeetings(buildServerFilters());
    renderMessage("success", `${result.synced} Google Meet records synced.`);
    showSuccess("Google Meet sync complete.");
    await loadMeetings({ syncGoogle: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to sync Google Meet records.";
    renderMessage("error", message);
    showError(message);
  }
});

meetingTableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  await handleMeetingAction(button.dataset.action, button.dataset.meetingId);
});

bootPage({
  pageKey: "meeting-details",
  title: pageTitles["meeting-details"],
  subtitle: "Sync, review, reschedule, and delete Google Meet calendar events.",
});

loadMeetings();
window.setInterval(() => loadMeetings({ syncGoogle: false }), frontendConfig.refreshIntervals.meetingsMs);
