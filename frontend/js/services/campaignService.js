import { apiService } from "./api.js";

export const campaignService = {
  listCampaigns() {
    return apiService.get("/campaigns");
  },

  getCampaign(campaignId) {
    return apiService.get(`/campaigns/${campaignId}`);
  },

  getCampaignContacts(campaignId) {
    return apiService.get(`/campaigns/${campaignId}/contacts`);
  },

  getCampaignData(campaignId) {
    return apiService.get(`/campaigns/${campaignId}/data`);
  },

  previewLeads(file) {
    const formData = new FormData();
    formData.append("file", file);
    return apiService.postFormData("/campaigns/preview-leads", formData);
  },

  previewCsv(file) {
    return this.previewLeads(file);
  },

  createCampaign(payload) {
    return apiService.post("/campaigns", payload);
  },

  startCampaign(campaignId) {
    return apiService.post(`/campaigns/${campaignId}/start`);
  },

  pauseCampaign(campaignId) {
    return apiService.post(`/campaigns/${campaignId}/pause`);
  },

  resumeCampaign(campaignId) {
    return apiService.post(`/campaigns/${campaignId}/resume`);
  },

  stopCampaign(campaignId) {
    return apiService.post(`/campaigns/${campaignId}/stop`);
  },

  deleteCampaign(campaignId) {
    return apiService.delete(`/campaigns/${campaignId}`);
  },
};
