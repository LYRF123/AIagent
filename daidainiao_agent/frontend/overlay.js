import { sidebar, sidebarToggle, settingsButton, workspaceToggle } from "./state.js";

let settingsCloseTimer = null;
let settingsFocusTrapHandler = null;
let workspaceFocusTrapHandler = null;
let settingsShellActive = false;
let modalBackdropDepth = 0;

function conversationPanel() {
  return document.querySelector(".conversation-panel");
}

function workspacePanel() {
  return document.getElementById("workspace-panel");
}

function settingsPanel() {
  return document.getElementById("settings-panel");
}

export function isSettingsPanelOpen() {
  const panel = settingsPanel();
  return Boolean(panel && !panel.hidden && !panel.classList?.contains("settings-panel-closing"));
}

function syncWorkspacePanelInert() {
  const panel = workspacePanel();
  if (!panel) return;
  const workspaceOpen = panel.classList?.contains("workspace-open") ?? false;
  if (isSettingsPanelOpen() || !workspaceOpen) {
    panel.setAttribute("inert", "");
    panel.setAttribute("aria-hidden", "true");
    return;
  }
  panel.removeAttribute("inert");
  panel.setAttribute("aria-hidden", "false");
}

function applyShellInert() {
  const active = settingsShellActive || modalBackdropDepth > 0;
  sidebar?.toggleAttribute("inert", active);
  sidebarToggle?.toggleAttribute("inert", active);
  conversationPanel()?.toggleAttribute("inert", active);
  // Legacy: clear whole main-content inert from older builds.
  document.getElementById("main-content")?.removeAttribute("inert");
  syncWorkspacePanelInert();
}

export function setSettingsShellInert(active) {
  settingsShellActive = active;
  applyShellInert();
}

export function setWorkspaceShellInert(active) {
  sidebar?.toggleAttribute("inert", active);
  sidebarToggle?.toggleAttribute("inert", active);
  conversationPanel()?.toggleAttribute("inert", active);
}

export function setModalBackdropInert(active) {
  modalBackdropDepth += active ? 1 : -1;
  if (modalBackdropDepth < 0) modalBackdropDepth = 0;
  applyShellInert();
}

function clearInert(el) {
  if (!el) return;
  if (typeof el.removeAttribute === "function") {
    el.removeAttribute("inert");
    return;
  }
  if ("inert" in el) {
    el.inert = false;
  }
}

function setInert(el, active) {
  if (!el) return;
  if (typeof el.toggleAttribute === "function") {
    el.toggleAttribute("inert", active);
    return;
  }
  if ("inert" in el) {
    el.inert = active;
  }
}

export function clearShellInert() {
  settingsShellActive = false;
  modalBackdropDepth = 0;
  clearInert(sidebar);
  clearInert(sidebarToggle);
  clearInert(conversationPanel());
  clearInert(document.getElementById("main-content"));
  syncWorkspacePanelInert();
}

export function showWorkspaceScrim(visible) {
  const scrim = document.getElementById("workspace-scrim");
  if (!scrim) return;
  scrim.hidden = !visible;
  scrim.setAttribute("aria-hidden", String(!visible));
}

export function dismissSettingsPanelAnimated(onDone) {
  const panel = settingsPanel();
  if (!panel || panel.hidden || panel.classList.contains("settings-panel-closing")) {
    onDone?.();
    return;
  }
  panel.classList.add("settings-panel-closing");
  clearTimeout(settingsCloseTimer);
  settingsCloseTimer = setTimeout(() => {
    panel.hidden = true;
    panel.classList.remove("settings-panel-closing");
    setSettingsShellInert(false);
    removeSettingsFocusTrap();
    syncWorkspacePanelInert();
    onDone?.();
  }, 260);
}

export function bindSettingsFocusTrap(panel) {
  removeSettingsFocusTrap();
  const card = panel?.querySelector(".settings-card");
  if (!card) return;
  const ref = { current: null };
  bindFocusTrap(ref, card, () => panel.hidden);
  settingsFocusTrapHandler = ref.current;
}

export function removeSettingsFocusTrap() {
  if (settingsFocusTrapHandler) {
    document.removeEventListener("keydown", settingsFocusTrapHandler);
    settingsFocusTrapHandler = null;
  }
}

export function bindWorkspaceFocusTrap(panel) {
  removeWorkspaceFocusTrap();
  if (!panel) return;
  const ref = { current: null };
  bindFocusTrap(ref, panel, () => !panel.classList.contains("workspace-open"));
  workspaceFocusTrapHandler = ref.current;
}

export function removeWorkspaceFocusTrap() {
  if (workspaceFocusTrapHandler) {
    document.removeEventListener("keydown", workspaceFocusTrapHandler);
    workspaceFocusTrapHandler = null;
  }
}

function getFocusables(root) {
  if (!root) return [];
  return [...root.querySelectorAll(
    'button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )];
}

function bindFocusTrap(handlerRef, root, panelHiddenCheck) {
  if (handlerRef.current) {
    document.removeEventListener("keydown", handlerRef.current);
  }
  const handler = (event) => {
    if (event.key !== "Tab" || panelHiddenCheck()) return;
    const focusables = getFocusables(root);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  handlerRef.current = handler;
  document.addEventListener("keydown", handler);
}

export function focusSettingsCloseButton() {
  document.getElementById("settings-close")?.focus();
}

export function focusWorkspaceCloseButton() {
  document.getElementById("workspace-close")?.focus();
}

export function focusWorkspaceToggle() {
  workspaceToggle?.focus();
}

export function focusSettingsButton() {
  settingsButton?.focus();
}
