import { apiService } from "./api.js";

export const callService = {
  listAgents() {
    return apiService.get("/agents");
  },

  listCalls() {
    return apiService.get("/calls");
  },

  getCall(callId) {
    return apiService.get(`/calls/${callId}`);
  },

  startIndividualCall(payload) {
    return apiService.post("/calls/individual", payload);
  },

  deleteCall(callId) {
    return apiService.delete(`/calls/${callId}`);
  },
};
