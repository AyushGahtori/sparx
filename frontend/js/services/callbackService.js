import { apiService } from "./api.js";

export const callbackService = {
  listCallbacks(filters = {}) {
    return apiService.get("/callbacks", filters);
  },

  getCallback(callbackId) {
    return apiService.get(`/callbacks/${callbackId}`);
  },

  createCallback(payload) {
    return apiService.post("/callbacks", payload);
  },

  updateCallback(callbackId, payload) {
    return apiService.put(`/callbacks/${callbackId}`, payload);
  },

  rescheduleCallback(callbackId, payload) {
    return apiService.post(`/callbacks/${callbackId}/reschedule`, payload);
  },

  executeCallback(callbackId) {
    return apiService.post(`/callbacks/${callbackId}/execute`);
  },

  deleteCallback(callbackId) {
    return apiService.delete(`/callbacks/${callbackId}`);
  },
};
