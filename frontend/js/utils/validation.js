const phonePattern = /^\+[1-9]\d{7,14}$/;

export function collectFormValues(form) {
  const formData = new FormData(form);
  return Object.fromEntries(formData.entries());
}

export function validatePhoneE164(phone) {
  return phonePattern.test(String(phone || "").trim());
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
  if (!value) {
    return undefined;
  }
  return new Date(`${value}T00:00:00`).toISOString();
}

export function toIsoRangeEnd(value) {
  if (!value) {
    return undefined;
  }
  return new Date(`${value}T23:59:59`).toISOString();
}
