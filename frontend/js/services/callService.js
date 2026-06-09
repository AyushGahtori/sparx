import { apiService } from "./api.js";

export const callService = {
  listAgents() {
    return apiService.get("/agents");
  },

  listCalls() {
    return apiService.get("/calls");
  },

  listRecordings() {
    return apiService.get("/calls/recordings");
  },

  getCall(callId) {
    return apiService.get(`/calls/${callId}`);
  },

  getRecordingAudio(callId) {
    return apiService.getBlob(`/calls/${callId}/recording/audio`);
  },

  startIndividualCall(payload) {
    return apiService.post("/calls/individual", payload);
  },

  deleteCall(callId) {
    return apiService.delete(`/calls/${callId}`);
  },
};
