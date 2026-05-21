import {
  sessionSidebarStorageKey,
  compactSessionSidebarQuery,
  appShell,
  sidebarToggle,
  sidebar,
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
  if (!appShell || !sidebarToggle) {
    return;
  }

  const isOpen = Boolean(nextIsOpen);
  const shouldPersist = options.persist !== false;
  appShell.classList.toggle("sidebar-collapsed", !isOpen);
  sidebarToggle.setAttribute("aria-expanded", String(isOpen));
  sidebarToggle.setAttribute("aria-label", isOpen ? "关闭侧栏" : "打开侧栏");

  if (sidebar) {
    sidebar.setAttribute("aria-hidden", String(!isOpen));
    if ("inert" in sidebar) {
      sidebar.inert = !isOpen;
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
