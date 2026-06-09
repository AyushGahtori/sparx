import { apiService } from "./api.js";

export const meetingService = {
  listMeetings(filters = {}) {
    return apiService.get("/meetings", filters);
  },

  syncMeetings(filters = {}) {
    return apiService.post(`/meetings/sync${buildQuery(filters)}`);
  },

  rescheduleMeeting(meetingId, payload) {
    return apiService.post(`/meetings/${meetingId}/reschedule`, payload);
  },

  markMeetingDone(meetingId) {
    return apiService.post(`/meetings/${meetingId}/done`);
  },

  cancelMeeting(meetingId, payload) {
    return apiService.post(`/meetings/${meetingId}/cancel`, payload);
  },

  deleteMeeting(meetingId) {
    return apiService.delete(`/meetings/${meetingId}`);
  },
};

function buildQuery(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}
