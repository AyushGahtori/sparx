import { apiService } from "./api.js";

export const scheduledCallService = {
  listScheduledCalls(filters = {}) {
    return apiService.get("/scheduled-calls", filters);
  },

  scheduleCall(payload) {
    return apiService.post("/actions/schedule-call", payload);
  },
};
