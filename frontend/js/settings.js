import { bootPage } from "./app.js";
import { frontendConfig, pageTitles } from "./config.js";
import { apiService } from "./services/api.js";
import { escapeHtml } from "./utils/formatter.js";
import { showError, showSuccess } from "./utils/notifications.js";

const healthRoot = document.getElementById("settings-health");
const googleOAuthRoot = document.getElementById("google-oauth-panel");

function renderHealth(health) {
  const queueRows = Object.entries(health.queues || {})
    .map(([queueName, queueState]) => `
      <div class="detail-row">
        <span class="detail-label">${escapeHtml(queueName.replace(/_/g, " "))}</span>
        <span>${escapeHtml(`${queueState.status} | active ${queueState.active_items} | recovered ${queueState.recovered_items}`)}</span>
      </div>
    `)
    .join("");

  healthRoot.innerHTML = `
    <div class="detail-list">
      <div class="detail-row"><span class="detail-label">Overall Status</span><span>${escapeHtml(health.status)}</span></div>
      <div class="detail-row"><span class="detail-label">Backend</span><span>${escapeHtml(health.backend)}</span></div>
      <div class="detail-row"><span class="detail-label">Firebase</span><span>${escapeHtml(health.firebase)}</span></div>
      <div class="detail-row"><span class="detail-label">Twilio</span><span>${escapeHtml(health.twilio)}</span></div>
      <div class="detail-row"><span class="detail-label">Deepgram</span><span>${escapeHtml(health.deepgram)}</span></div>
      <div class="detail-row"><span class="detail-label">Gemma</span><span>${escapeHtml(health.gemma || "unknown")}</span></div>
      <div class="detail-row"><span class="detail-label">Campaign Queue</span><span>${escapeHtml(health.campaign_queue || "unknown")}</span></div>
      <div class="detail-row"><span class="detail-label">Callback Queue</span><span>${escapeHtml(health.callback_queue || "unknown")}</span></div>
      <div class="detail-row"><span class="detail-label">AI Queue</span><span>${escapeHtml(health.ai_queue || "unknown")}</span></div>
      <div class="detail-row"><span class="detail-label">CPU Usage</span><span>${escapeHtml(String(health.cpu_usage_percent ?? 0))}%</span></div>
      <div class="detail-row"><span class="detail-label">Memory Usage</span><span>${escapeHtml(String(health.memory_usage_mb ?? 0))} MB</span></div>
      <div class="detail-row"><span class="detail-label">Uptime</span><span>${escapeHtml(health.uptime || "-")}</span></div>
      <div class="detail-row"><span class="detail-label">Environment</span><span>${escapeHtml(health.environment || "local")}</span></div>
      ${queueRows}
    </div>
  `;
}

async function loadHealth() {
  try {
    const health = await apiService.get("/system/health");
    renderHealth(health);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load health.";
    healthRoot.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
  }
}

function renderGoogleOAuthStatus(status) {
  const configured = Boolean(status.configured);
  const connected = Boolean(status.connected);
  const pillClass = connected ? "connected" : configured ? "pending" : "not_configured";
  const pillText = connected ? "Connected" : configured ? "Ready to connect" : "Not configured";
  const scopes = Array.isArray(status.scopes) ? status.scopes : [];
  const defaultOwnerEmail = status.default_calendar_owner?.email || status.default_calendar_owner?.uid || "-";

  googleOAuthRoot.innerHTML = `
    <div class="detail-list">
      <div class="detail-row">
        <span class="detail-label">Status</span>
        <span class="status-pill ${pillClass}">${escapeHtml(pillText)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Redirect URI</span>
        <span>${escapeHtml(status.redirect_uri || "-")}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Scopes</span>
        <span>${escapeHtml(scopes.join(", ") || "-")}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Calendar Owner</span>
        <span>${escapeHtml(defaultOwnerEmail)}</span>
      </div>
    </div>
    <div class="form-actions">
      <button id="google-connect-button" class="button primary" type="button" ${configured ? "" : "disabled"}>${connected ? "Reconnect Google" : "Connect Google"}</button>
      <button id="google-disconnect-button" class="button secondary" type="button" ${connected ? "" : "disabled"}>Disconnect</button>
    </div>
  `;

  document.getElementById("google-connect-button")?.addEventListener("click", connectGoogleOAuth);
  document.getElementById("google-disconnect-button")?.addEventListener("click", disconnectGoogleOAuth);
}

async function loadGoogleOAuthStatus() {
  try {
    const status = await apiService.get("/auth/google/status");
    renderGoogleOAuthStatus(status);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load Google OAuth status.";
    googleOAuthRoot.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
  }
}

async function connectGoogleOAuth() {
  try {
    const result = await apiService.get("/auth/google/login");
    if (!result.authorization_url) {
      throw new Error("Google authorization URL was not returned.");
    }
    window.location.href = result.authorization_url;
  } catch (error) {
    showError(error instanceof Error ? error.message : "Unable to start Google OAuth.");
  }
}

async function disconnectGoogleOAuth() {
  try {
    await apiService.delete("/auth/google/disconnect");
    showSuccess("Google Calendar disconnected.");
    await loadGoogleOAuthStatus();
  } catch (error) {
    showError(error instanceof Error ? error.message : "Unable to disconnect Google Calendar.");
  }
}

function handleGoogleOAuthRedirectMessage() {
  const params = new URLSearchParams(window.location.search);
  const status = params.get("google_oauth");
  if (!status) {
    return;
  }
  if (status === "connected") {
    showSuccess("Google Calendar connected.");
  } else if (status === "error") {
    showError("Google OAuth failed. Please try connecting again.");
  }
  params.delete("google_oauth");
  const cleanUrl = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ""}`;
  window.history.replaceState({}, "", cleanUrl);
}

function bindOperatorLinks() {
  const docsLink = document.getElementById("api-docs-link");
  if (docsLink instanceof HTMLAnchorElement) {
    docsLink.href = frontendConfig.docsUrl || frontendConfig.apiBaseUrl;
  }
}

bootPage({
  pageKey: "settings",
  title: pageTitles.settings,
  subtitle: "Runtime diagnostics, dependency health, and operator shortcuts.",
});

loadHealth();
handleGoogleOAuthRedirectMessage();
bindOperatorLinks();
loadGoogleOAuthStatus();
window.setInterval(loadHealth, 20000);
