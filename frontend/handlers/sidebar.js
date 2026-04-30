import {
  sessionSidebarStorageKey,
  compactSessionSidebarQuery,
  appShell,
  sessionSidebarToggle,
  sessionSidebar,
} from "../state.js";

export function getStoredSessionSidebarState() {
  try {
    const value = window.localStorage.getItem(sessionSidebarStorageKey);
    if (value === "true") {
      return true;
    }
    if (value === "false") {
      return false;
    }
  } catch {
    return null;
  }
  return null;
}

export function shouldStartWithSessionSidebarOpen() {
  const storedValue = getStoredSessionSidebarState();
  if (storedValue !== null) {
    return storedValue;
  }
  return !compactSessionSidebarQuery.matches;
}

export function setSessionSidebarOpen(nextIsOpen, options = {}) {
  if (!appShell || !sessionSidebarToggle) {
    return;
  }

  const isOpen = Boolean(nextIsOpen);
  const shouldPersist = options.persist !== false;
  appShell.classList.toggle("session-sidebar-open", isOpen);
  appShell.classList.toggle("session-sidebar-collapsed", !isOpen);
  sessionSidebarToggle.setAttribute("aria-expanded", String(isOpen));
  sessionSidebarToggle.setAttribute("aria-label", isOpen ? "\u5173\u95ED\u5386\u53F2\u4F1A\u8BDD\u4FA7\u680F" : "\u6253\u5F00\u5386\u53F2\u4F1A\u8BDD\u4FA7\u680F");

  if (sessionSidebar) {
    sessionSidebar.setAttribute("aria-hidden", String(!isOpen));
    if ("inert" in sessionSidebar) {
      sessionSidebar.inert = !isOpen;
    }
  }

  if (shouldPersist) {
    try {
      window.localStorage.setItem(sessionSidebarStorageKey, String(isOpen));
    } catch {
      // Local storage can be unavailable in strict browser contexts.
    }
  }
}

export function closeSessionSidebarOnSmallScreen() {
  if (compactSessionSidebarQuery.matches) {
    setSessionSidebarOpen(false);
  }
}
