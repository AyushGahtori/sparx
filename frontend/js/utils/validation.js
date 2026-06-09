import { indiaDateInputToIso } from "./formatter.js";

const phonePattern = /^\+[1-9]\d{7,14}$/;
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function collectFormValues(form) {
  const formData = new FormData(form);
  return Object.fromEntries(formData.entries());
}

export function validatePhoneE164(phone) {
  return phonePattern.test(String(phone || "").trim());
}

export function validateEmail(email) {
  return emailPattern.test(String(email || "").trim());
}

export function requireFields(payload, requiredFieldMap) {
  const missingLabels = [];

  Object.entries(requiredFieldMap).forEach(([field, label]) => {
    const value = payload[field];
    if (value === undefined || value === null || String(value).trim() === "") {
      missingLabels.push(label);
    }
  });

  if (missingLabels.length) {
    throw new Error(`Please complete the required fields: ${missingLabels.join(", ")}.`);
  }
}

export function normalizeOptionalString(value) {
  if (value === undefined || value === null) {
    return undefined;
  }
  const trimmed = String(value).trim();
  return trimmed || undefined;
}

export function toIsoRangeStart(value) {
  return indiaDateInputToIso(value, false);
}

export function toIsoRangeEnd(value) {
  return indiaDateInputToIso(value, true);
}
