const runtimeConfig = window.SPARX_CONFIG || {};
const runtimeAuthConfig = runtimeConfig.auth || {};
const runtimeFirebaseConfig = runtimeConfig.firebaseConfig || {};

function deriveDocsUrl(apiBaseUrl) {
  if (!apiBaseUrl) {
    return "";
  }
  return apiBaseUrl.endsWith("/api") ? `${apiBaseUrl.slice(0, -4)}/docs` : `${apiBaseUrl}/docs`;
}

export const frontendConfig = Object.freeze({
  appName: "SPARX AI Agent Calling Module",
  apiBaseUrl: runtimeConfig.apiBaseUrl || "http://127.0.0.1:8000/api",
  docsUrl: runtimeConfig.docsUrl || deriveDocsUrl(runtimeConfig.apiBaseUrl || "http://127.0.0.1:8000/api"),
  requestTimeoutMs: Number(runtimeConfig.requestTimeoutMs || 20000),
  environmentLabel: runtimeConfig.environmentLabel || "Local",
  auth: Object.freeze({
    enabled: Boolean(runtimeAuthConfig.enabled || runtimeFirebaseConfig.apiKey),
    required: Boolean(runtimeAuthConfig.required),
    firebaseConfig: Object.freeze({
      apiKey: runtimeFirebaseConfig.apiKey || "",
      authDomain: runtimeFirebaseConfig.authDomain || "",
      projectId: runtimeFirebaseConfig.projectId || "",
      appId: runtimeFirebaseConfig.appId || "",
      storageBucket: runtimeFirebaseConfig.storageBucket || "",
      messagingSenderId: runtimeFirebaseConfig.messagingSenderId || "",
    }),
  }),
  refreshIntervals: Object.freeze({
    dashboardMs: 20000,
    manualCallMs: 8000,
    campaignsMs: 15000,
    callbacksMs: 12000,
    meetingsMs: 15000,
    summariesMs: 15000,
    callHistoryMs: 15000,
    recordingsMs: 15000,
  }),
});

export const pageTitles = Object.freeze({
  home: "SPARX Control Center",
  dashboard: "Dashboard",
  "manual-call": "Manual AI Calling",
  campaigns: "Campaign Management",
  callbacks: "Callback Queue",
  "meeting-details": "Meeting Details",
  "call-history": "Call History",
  "call-recordings": "Call Recording",
  summaries: "AI Summaries",
  settings: "Diagnostics",
});
