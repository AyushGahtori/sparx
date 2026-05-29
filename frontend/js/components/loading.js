export function loadingState(message = "Loading...") {
  return `<div class="loading-state">${message}</div>`;
}

export function emptyState(message = "No data available.") {
  return `<div class="empty-state">${message}</div>`;
}

export function errorState(message = "Something went wrong.") {
  return `<div class="error-state">${message}</div>`;
}
