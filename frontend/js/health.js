import { apiService } from "../services/api.js";

function buildStatusPill(status) {
  return `<span class="status-pill ${status}">${status.replace("_", " ")}</span>`;
}

function buildServiceCard(name, detail) {
  return `
    <div class="status-card">
      <div class="meta-row">
        <strong>${name}</strong>
        ${buildStatusPill(detail.status)}
      </div>
      <div class="detail-line">${detail.message}</div>
    </div>
  `;
}

function buildHealthMarkup(health) {
  return `
    <div class="meta-row">
      ${buildStatusPill(health.status)}
      <span><strong>Environment:</strong> ${health.environment}</span>
      <span><strong>Uptime:</strong> ${health.uptime}</span>
    </div>
    <div class="detail-line"><strong>Timestamp:</strong> ${health.timestamp}</div>
    <div class="status-grid">
      ${buildServiceCard("Firebase", health.details.firebase)}
      ${buildServiceCard("Twilio", health.details.twilio)}
      ${buildServiceCard("Deepgram", health.details.deepgram)}
      ${health.details.gemma ? buildServiceCard("Gemma", health.details.gemma) : ""}
    </div>
  `;
}

export async function mountHealthStatus(elementId) {
  const target = document.getElementById(elementId);
  if (!target) {
    return;
  }

  target.textContent = "Loading backend health...";

  try {
    const health = await apiService.get("/health");
    target.innerHTML = buildHealthMarkup(health);
  } catch (error) {
    target.innerHTML = `
      <div class="status-card">
        <div class="meta-row">
          ${buildStatusPill("unavailable")}
        </div>
        <div class="detail-line">${error.message}</div>
      </div>
    `;
  }
}
