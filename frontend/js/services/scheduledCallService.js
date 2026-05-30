import { apiService } from "./api.js";

export const scheduledCallService = {
  listScheduledCalls(filters = {}) {
    return apiService.get("/scheduled-calls", filters);
  },

  scheduleCall(payload) {
    return apiService.post("/actions/schedule-call", payload);
  },

  updateScheduledCallStatus(scheduledCallId, payload) {
    return apiService.put(`/scheduled-calls/${scheduledCallId}/status`, payload);
  },
};
