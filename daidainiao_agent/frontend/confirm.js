import { escapeHtml } from "./render/escape.js";
import { setModalBackdropInert } from "./overlay.js";

function ensureConfirmDialog() {
  let dialog = document.getElementById("app-confirm");
  if (dialog) return dialog;

  dialog = document.createElement("div");
  dialog.id = "app-confirm";
  dialog.className = "app-confirm";
  dialog.hidden = true;
  dialog.innerHTML = `
    <div class="app-confirm-card" role="dialog" aria-modal="true" aria-labelledby="app-confirm-title">
      <div class="app-confirm-body">
        <h3 id="app-confirm-title"></h3>
        <p id="app-confirm-message"></p>
      </div>
      <div class="app-confirm-actions">
        <button class="ghost-button compact-button app-confirm-cancel" type="button">取消</button>
        <button class="primary-button compact-button app-confirm-ok" type="button">确认</button>
      </div>
    </div>
  `;
  document.body.appendChild(dialog);
  return dialog;
}

function finishWithClick(button, callback) {
  button.classList.remove("app-confirm-clicked");
  void button.offsetWidth;
  button.classList.add("app-confirm-clicked");
  window.setTimeout(callback, 190);
}

export function confirmAction({
  title = "确认操作",
  message = "",
  confirmText = "确认",
  cancelText = "取消",
  tone = "normal",
} = {}) {
  const dialog = ensureConfirmDialog();
  const titleEl = dialog.querySelector("#app-confirm-title");
  const messageEl = dialog.querySelector("#app-confirm-message");
  const cancelButton = dialog.querySelector(".app-confirm-cancel");
  const okButton = dialog.querySelector(".app-confirm-ok");

  titleEl.textContent = title;
  messageEl.innerHTML = escapeHtml(message);
  cancelButton.textContent = cancelText;
  okButton.textContent = confirmText;
  okButton.dataset.tone = tone;
  cancelButton.classList.remove("app-confirm-clicked");
  okButton.classList.remove("app-confirm-clicked");
  dialog.hidden = false;
  setModalBackdropInert(true);
  cancelButton.focus();

  return new Promise((resolve) => {
    const cleanup = (value) => {
      dialog.hidden = true;
      setModalBackdropInert(false);
      dialog.removeEventListener("click", onBackdrop);
      cancelButton.removeEventListener("click", onCancel);
      okButton.removeEventListener("click", onConfirm);
      document.removeEventListener("keydown", onKeydown);
      resolve(value);
    };

    const onBackdrop = (event) => {
      if (event.target === dialog) {
        finishWithClick(cancelButton, () => cleanup(false));
      }
    };
    const onCancel = () => finishWithClick(cancelButton, () => cleanup(false));
    const onConfirm = () => finishWithClick(okButton, () => cleanup(true));
    const onKeydown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finishWithClick(cancelButton, () => cleanup(false));
      }
    };

    dialog.addEventListener("click", onBackdrop);
    cancelButton.addEventListener("click", onCancel);
    okButton.addEventListener("click", onConfirm);
    document.addEventListener("keydown", onKeydown);
  });
}
