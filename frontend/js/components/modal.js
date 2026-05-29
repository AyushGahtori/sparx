import { escapeHtml } from "../utils/formatter.js";

function ensureModalRoot() {
  let root = document.getElementById("modal-root");
  if (!root) {
    root = document.createElement("div");
    root.id = "modal-root";
    root.className = "modal-root";
    document.body.appendChild(root);
  }
  return root;
}

function closeModal(root) {
  root.classList.remove("is-open");
  root.innerHTML = "";
}

function openModal({ title, bodyHtml, footerHtml = "" }) {
  const root = ensureModalRoot();
  root.innerHTML = `
    <div class="modal-backdrop" data-modal-close="true"></div>
    <div class="modal-dialog" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
      <div class="modal-header panel-header">
        <div>
          <h2>${escapeHtml(title)}</h2>
        </div>
        <button class="button ghost small" type="button" data-modal-close="true">Close</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      <div class="modal-footer header-actions">${footerHtml}</div>
    </div>
  `;
  root.classList.add("is-open");
  root.onclick = (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.modalClose === "true") {
      closeModal(root);
    }
  };
  return root;
}

export function showContentDialog({ title, bodyHtml, footerHtml = "" }) {
  const root = openModal({ title, bodyHtml, footerHtml });
  return {
    close: () => closeModal(root),
  };
}

export function confirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  confirmVariant = "primary",
  cancelLabel = "Cancel",
}) {
  return new Promise((resolve) => {
    const footerHtml = `
      <button class="button ghost" type="button" data-modal-action="cancel">${escapeHtml(cancelLabel)}</button>
      <button class="button ${escapeHtml(confirmVariant)}" type="button" data-modal-action="confirm">${escapeHtml(confirmLabel)}</button>
    `;
    const root = openModal({
      title,
      bodyHtml: `<p class="muted-text">${escapeHtml(message)}</p>`,
      footerHtml,
    });

    const handleClick = (event) => {
      const shouldClose = event.target instanceof HTMLElement && event.target.dataset.modalClose === "true";
      const action = event.target instanceof HTMLElement ? event.target.dataset.modalAction : null;
      if (!action && !shouldClose) {
        return;
      }

      root.removeEventListener("click", handleClick);
      closeModal(root);
      resolve(action === "confirm");
    };

    root.addEventListener("click", handleClick);
  });
}

export function promptDialog({
  title,
  label,
  defaultValue = "",
  placeholder = "",
  confirmLabel = "Save",
}) {
  return new Promise((resolve) => {
    const bodyHtml = `
      <div class="form-field">
        <label for="modal-prompt-input">${escapeHtml(label)}</label>
        <input
          id="modal-prompt-input"
          type="text"
          value="${escapeHtml(defaultValue)}"
          placeholder="${escapeHtml(placeholder)}"
        >
      </div>
    `;
    const footerHtml = `
      <button class="button ghost" type="button" data-modal-action="cancel">Cancel</button>
      <button class="button primary" type="button" data-modal-action="confirm">${escapeHtml(confirmLabel)}</button>
    `;
    const root = openModal({ title, bodyHtml, footerHtml });
    const input = root.querySelector("#modal-prompt-input");
    if (input instanceof HTMLInputElement) {
      input.focus();
      input.select();
    }

    const handleClick = (event) => {
      const shouldClose = event.target instanceof HTMLElement && event.target.dataset.modalClose === "true";
      const action = event.target instanceof HTMLElement ? event.target.dataset.modalAction : null;
      if (!action && !shouldClose) {
        return;
      }

      root.removeEventListener("click", handleClick);
      if (action === "cancel" || shouldClose) {
        closeModal(root);
        resolve(null);
        return;
      }

      const value = input instanceof HTMLInputElement ? input.value.trim() : "";
      closeModal(root);
      resolve(value || null);
    };

    root.addEventListener("click", handleClick);
  });
}
