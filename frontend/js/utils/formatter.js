export const INDIA_TIME_ZONE = "Asia/Kolkata";
const INDIA_OFFSET = "+05:30";

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

  const date = parseAppDate(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return date.toLocaleString("en-IN", {
    timeZone: INDIA_TIME_ZONE,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

export function formatDate(value, fallback = "Not available") {
  if (!value) {
    return fallback;
  }

  const date = parseAppDate(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return date.toLocaleDateString("en-IN", {
    timeZone: INDIA_TIME_ZONE,
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
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

  const date = parseAppDate(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const parts = getIndiaDateParts(date);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function toLocalDateTimeInputValue(value = new Date()) {
  const date = parseAppDate(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const parts = getIndiaDateParts(date, true);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function indiaDateInputToIso(value, endOfDay = false) {
  if (!value) {
    return undefined;
  }
  const time = endOfDay ? "23:59:59" : "00:00:00";
  return new Date(`${value}T${time}${INDIA_OFFSET}`).toISOString();
}

export function indiaDateTimeInputToIso(value) {
  if (!value) {
    return undefined;
  }
  return new Date(`${value}:00${INDIA_OFFSET}`).toISOString();
}

export function isAfterNowInIndia(value) {
  const date = parseAppDate(value);
  return !Number.isNaN(date.getTime()) && date.getTime() >= Date.now();
}

export function parseAppDate(value) {
  if (value instanceof Date) {
    return value;
  }
  if (typeof value !== "string") {
    return new Date(value);
  }

  const trimmed = value.trim();
  const hasTime = /T\d{2}:\d{2}/.test(trimmed);
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  if (hasTime && !hasTimezone) {
    return new Date(`${trimmed}Z`);
  }
  return new Date(trimmed);
}

function getIndiaDateParts(date, includeTime = false) {
  const options = {
    timeZone: INDIA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(includeTime
      ? {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          hourCycle: "h23",
        }
      : {}),
  };
  const parts = new Intl.DateTimeFormat("en-CA", options).formatToParts(date);
  const partMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    year: partMap.year,
    month: partMap.month,
    day: partMap.day,
    hour: partMap.hour || "00",
    minute: partMap.minute || "00",
  };
}
