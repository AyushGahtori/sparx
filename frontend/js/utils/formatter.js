export function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatDateTime(value, fallback = "Not available") {
  if (!value) {
    return fallback;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return date.toLocaleString();
}

export function formatDate(value, fallback = "Not available") {
  if (!value) {
    return fallback;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return date.toLocaleDateString();
}

export function formatDuration(seconds, fallback = "0s") {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) {
    return fallback;
  }

  const totalSeconds = Math.max(0, Number(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;

  if (minutes === 0) {
    return `${remainingSeconds}s`;
  }

  return `${minutes}m ${remainingSeconds}s`;
}

export function formatPercent(value, fallback = "0%") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return fallback;
  }

  return `${Number(value).toFixed(0)}%`;
}

export function formatScore(value, fallback = "-") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return fallback;
  }
  return `${Math.round(Number(value))}`;
}

export function formatStatusLabel(value, fallback = "-") {
  if (!value) {
    return fallback;
  }
  return String(value).replace(/_/g, " ");
}

export function truncateText(value, maxLength = 120, fallback = "-") {
  if (!value) {
    return fallback;
  }
  const text = String(value);
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1)}...`;
}

export function toLocalDateInputValue(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toISOString().slice(0, 10);
}

export function toLocalDateTimeInputValue(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const timezoneOffsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - timezoneOffsetMs).toISOString().slice(0, 16);
}
