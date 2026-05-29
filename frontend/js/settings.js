import { bootPage } from "./app.js";
import { pageTitles } from "./config.js";
import { apiService } from "./services/api.js";
import { escapeHtml } from "./utils/formatter.js";

const healthRoot = document.getElementById("settings-health");

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

bootPage({
  pageKey: "settings",
  title: pageTitles.settings,
  subtitle: "Runtime diagnostics, dependency health, and operator shortcuts.",
});

loadHealth();
window.setInterval(loadHealth, 20000);
