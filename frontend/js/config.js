const runtimeConfig = window.SPARX_CONFIG || {};

export const frontendConfig = Object.freeze({
  appName: "SPARX AI Agent Calling Module",
  apiBaseUrl: runtimeConfig.apiBaseUrl || "http://127.0.0.1:8000/api",
  requestTimeoutMs: Number(runtimeConfig.requestTimeoutMs || 20000),
  environmentLabel: runtimeConfig.environmentLabel || "Local",
  refreshIntervals: Object.freeze({
    dashboardMs: 20000,
    manualCallMs: 8000,
    campaignsMs: 15000,
    scheduledCallsMs: 15000,
    callbacksMs: 12000,
    summariesMs: 15000,
    callHistoryMs: 15000,
  }),
});

export const pageTitles = Object.freeze({
  home: "SPARX Control Center",
  dashboard: "Dashboard",
  "manual-call": "Manual AI Calling",
  campaigns: "Campaign Management",
  "scheduled-calls": "Scheduled Calls",
  callbacks: "Callback Queue",
  "call-history": "Call History",
  summaries: "AI Summaries",
  settings: "Diagnostics",
});
