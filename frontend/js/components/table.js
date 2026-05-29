import { errorState, loadingState } from "./loading.js";

export function renderTableBodyState(tbody, colspan, markup) {
  tbody.innerHTML = `<tr><td colspan="${colspan}">${markup}</td></tr>`;
}

export function renderTableLoading(tbody, colspan, message = "Loading...") {
  renderTableBodyState(tbody, colspan, loadingState(message));
}

export function renderTableError(tbody, colspan, message) {
  renderTableBodyState(tbody, colspan, errorState(message));
}

export function renderTableEmpty(tbody, colspan, message) {
  renderTableBodyState(tbody, colspan, `<div class="table-empty">${message}</div>`);
}
