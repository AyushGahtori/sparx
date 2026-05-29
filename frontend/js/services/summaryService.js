import { apiService } from "./api.js";

export const summaryService = {
  listSummaries(filters = {}) {
    return apiService.get("/summaries", filters);
  },

  getSummary(callId) {
    return apiService.get(`/summaries/${callId}`);
  },

  deleteSummary(callId) {
    return apiService.delete(`/summaries/${callId}`);
  },
};
