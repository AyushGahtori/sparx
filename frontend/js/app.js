import { frontendConfig, pageTitles } from "./config.js";
import { renderNavbar } from "./components/navbar.js";
import { renderSidebar } from "./components/sidebar.js";
import { getCurrentPageKey, navigateTo } from "./router.js";
import { apiService } from "./services/api.js";
import { initialiseAuthShell } from "./services/auth.js";
import { emptyState } from "./components/loading.js";
import { formatDateTime, formatStatusLabel, truncateText, escapeHtml } from "./utils/formatter.js";
import { showError } from "./utils/notifications.js";

let globalErrorHandlersBound = false;
let designExperienceBound = false;

export function bootPage({ pageKey, title, subtitle }) {
  renderSidebar();
  renderNavbar({
    title,
    subtitle,
    rightMeta: `<span class="topbar-badge">${escapeHtml(frontendConfig.appName)}</span>`,
  });
  document.title = `${title} | SPARX`;
  document.body.dataset.page = pageKey;
  bindGlobalErrorHandlers();
  bindDesignExperience();
  void initialiseAuthShell();
}

function bindGlobalErrorHandlers() {
  if (globalErrorHandlersBound) {
    return;
  }

  window.addEventListener("unhandledrejection", (event) => {
    const message = event.reason instanceof Error ? event.reason.message : "Unexpected request failure.";
    showError(message);
  });

  window.addEventListener("error", (event) => {
    const message = event.error instanceof Error ? event.error.message : "Unexpected browser error.";
    showError(message);
  });

  globalErrorHandlersBound = true;
}

function bindDesignExperience() {
  applyStoredTheme();
  ensureCommandPalette();

  document.getElementById("theme-toggle-button")?.addEventListener("click", toggleTheme);
  document.getElementById("command-search-button")?.addEventListener("click", openCommandPalette);

  if (designExperienceBound) {
    return;
  }

  window.addEventListener("keydown", (event) => {
    const isCommandShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
    if (isCommandShortcut) {
      event.preventDefault();
      openCommandPalette();
    }
    if (event.key === "Escape") {
      closeCommandPalette();
    }
  });

  designExperienceBound = true;
}

function applyStoredTheme() {
  const storedTheme = window.localStorage.getItem("sparx-theme");
  const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const theme = storedTheme || (systemDark ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
}

function toggleTheme() {
  const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  window.localStorage.setItem("sparx-theme", nextTheme);
}

function ensureCommandPalette() {
  if (document.getElementById("command-palette")) {
    return;
  }

  const root = document.createElement("div");
  root.id = "command-palette";
  root.className = "command-palette";
  root.setAttribute("aria-hidden", "true");
  root.innerHTML = `
    <div class="command-panel" role="dialog" aria-modal="true" aria-label="Command palette">
      <input id="command-input" class="command-input" type="search" placeholder="Search SPARX workflows..." autocomplete="off">
      <div id="command-list" class="command-list"></div>
    </div>
  `;
  document.body.appendChild(root);

  root.addEventListener("click", (event) => {
    if (event.target === root) {
      closeCommandPalette();
    }
  });

  document.getElementById("command-input")?.addEventListener("input", renderCommandItems);
  document.getElementById("command-input")?.addEventListener("keydown", handleCommandInputKeydown);
  renderCommandItems();
}

function getCommandItems() {
  return [
    { key: "home", label: pageTitles.home, hint: "Control center overview" },
    { key: "dashboard", label: pageTitles.dashboard, hint: "KPI cards and operations dashboard" },
    { key: "manual-call", label: pageTitles["manual-call"], hint: "Start an individual AI call" },
    { key: "campaigns", label: pageTitles.campaigns, hint: "Create and operate campaigns" },
    { key: "callbacks", label: pageTitles.callbacks, hint: "Manage callback queue" },
    { key: "meeting-details", label: pageTitles["meeting-details"], hint: "Review meetings and follow-ups" },
    { key: "call-history", label: pageTitles["call-history"], hint: "Search call records" },
    { key: "call-recordings", label: pageTitles["call-recordings"], hint: "Play completed Twilio recordings" },
    { key: "summaries", label: pageTitles.summaries, hint: "Inspect AI summaries" },
    { key: "settings", label: pageTitles.settings, hint: "Diagnostics and integrations" },
  ];
}

function renderCommandItems() {
  const list = document.getElementById("command-list");
  const input = document.getElementById("command-input");
  if (!list) {
    return;
  }

  const query = input?.value?.trim().toLowerCase() || "";
  const items = getCommandItems().filter((item) => {
    const haystack = `${item.label} ${item.hint} ${item.key}`.toLowerCase();
    return haystack.includes(query);
  });

  list.innerHTML = items.length
    ? items
        .map(
          (item, index) => `
            <button class="command-item ${index === 0 ? "active" : ""}" type="button" data-command-page="${escapeHtml(item.key)}">
              <span><strong>${escapeHtml(item.label)}</strong><br><small>${escapeHtml(item.hint)}</small></span>
              <span class="topbar-kbd">Open</span>
            </button>
          `,
        )
        .join("")
    : `<div class="empty-state">No matching workflows found.</div>`;

  list.querySelectorAll("[data-command-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const pageKey = button instanceof HTMLElement ? button.dataset.commandPage : null;
      if (pageKey) {
        navigateTo(pageKey);
      }
    });
  });
}

function handleCommandInputKeydown(event) {
  const list = document.getElementById("command-list");
  if (!list) {
    return;
  }

  const items = Array.from(list.querySelectorAll(".command-item"));
  const activeIndex = items.findIndex((item) => item.classList.contains("active"));
  if (event.key === "Enter") {
    event.preventDefault();
    items[Math.max(activeIndex, 0)]?.click();
    return;
  }

  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
    return;
  }

  event.preventDefault();
  if (!items.length) {
    return;
  }

  const direction = event.key === "ArrowDown" ? 1 : -1;
  const nextIndex = (activeIndex + direction + items.length) % items.length;
  items.forEach((item) => item.classList.remove("active"));
  items[nextIndex].classList.add("active");
  items[nextIndex].scrollIntoView({ block: "nearest" });
}

function openCommandPalette() {
  ensureCommandPalette();
  const root = document.getElementById("command-palette");
  const input = document.getElementById("command-input");
  root?.classList.add("is-open");
  root?.setAttribute("aria-hidden", "false");
  if (input instanceof HTMLInputElement) {
    input.value = "";
    renderCommandItems();
    window.setTimeout(() => input.focus(), 0);
  }
}

function closeCommandPalette() {
  const root = document.getElementById("command-palette");
  root?.classList.remove("is-open");
  root?.setAttribute("aria-hidden", "true");
}

async function loadHomeOverview() {
  const healthTarget = document.getElementById("home-health");
  const modulesTarget = document.getElementById("home-modules");
  const callsTarget = document.getElementById("home-recent-calls");

  if (!healthTarget || !modulesTarget || !callsTarget) {
    return;
  }

  try {
    const [health, summaries, campaigns, callbacks] = await Promise.all([
      apiService.get("/health"),
      apiService.get("/summaries"),
      apiService.get("/campaigns"),
      apiService.get("/callbacks"),
    ]);

    healthTarget.innerHTML = `
      <div class="detail-list">
        <div class="detail-row"><span class="detail-label">Backend</span><span>${escapeHtml(health.backend)}</span></div>
        <div class="detail-row"><span class="detail-label">Firebase</span><span>${escapeHtml(health.firebase)}</span></div>
        <div class="detail-row"><span class="detail-label">Twilio</span><span>${escapeHtml(health.twilio)}</span></div>
        <div class="detail-row"><span class="detail-label">Deepgram</span><span>${escapeHtml(health.deepgram)}</span></div>
        <div class="detail-row"><span class="detail-label">Gemma</span><span>${escapeHtml(health.details?.gemma?.status || "unknown")}</span></div>
      </div>
    `;

    modulesTarget.innerHTML = `
      <div class="widget-list">
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Campaigns</span><span class="status-pill running">${campaigns.length}</span></div>
          <div class="detail-text">Bulk calling, queue control, and CSV ingestion are available.</div>
        </div>
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Callbacks</span><span class="status-pill scheduled">${callbacks.length}</span></div>
          <div class="detail-text">Time-aware callback scheduling and retry orchestration are available.</div>
        </div>
        <div class="widget-item">
          <div class="widget-item-header"><span class="widget-item-title">Summaries</span><span class="status-pill completed">${summaries.filter((item) => item.processed_by_ai).length}</span></div>
          <div class="detail-text">Gemma post-call intelligence is ready for processed calls.</div>
        </div>
      </div>
    `;

    const recentSummaries = summaries.slice(0, 4);
    if (!recentSummaries.length) {
      callsTarget.innerHTML = emptyState("No processed calls are available yet.");
      return;
    }

    callsTarget.innerHTML = `
      <div class="widget-list">
        ${recentSummaries
          .map(
            (item) => `
              <div class="widget-item">
                <div class="widget-item-header">
                  <span class="widget-item-title">${escapeHtml(item.lead_name)}</span>
                  <span class="status-pill ${escapeHtml(item.call_outcome || item.ai_processing_status)}">${escapeHtml(formatStatusLabel(item.call_outcome || item.ai_processing_status))}</span>
                </div>
                <div class="detail-text">${escapeHtml(truncateText(item.summary || item.next_action || "AI processing pending.", 120))}</div>
                <div class="detail-text">${escapeHtml(formatDateTime(item.call_date))}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load home overview.";
    healthTarget.innerHTML = `<div class="alert error">${escapeHtml(message)}</div>`;
    modulesTarget.innerHTML = emptyState("System data could not be loaded.");
    callsTarget.innerHTML = emptyState("Recent activity is unavailable.");
  }
}

function bindHomeActions() {
  document.querySelectorAll("[data-home-nav]").forEach((button) => {
    button.addEventListener("click", () => {
      const pageKey = button instanceof HTMLElement ? button.dataset.homeNav : null;
      if (pageKey) {
        navigateTo(pageKey);
      }
    });
  });
}

function initialiseHomePage() {
  const currentPageKey = getCurrentPageKey();
  if (currentPageKey !== "home") {
    return;
  }

  bootPage({
    pageKey: "home",
    title: pageTitles.home,
    subtitle: "Operate manual calls, campaigns, callbacks, and AI summaries from one place.",
  });
  bindHomeActions();
  loadHomeOverview();
}

initialiseHomePage();
