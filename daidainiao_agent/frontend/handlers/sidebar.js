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
  if (compactSessionSidebarQuery.matches) {
    return false;
  }
  const storedValue = getStoredSessionSidebarState();
  if (storedValue !== null) {
    return storedValue;
  }
  return !compactSessionSidebarQuery.matches;
}

function setSidebarInert(isInert) {
  if (!sidebar) return;
  if (isInert) {
    sidebar.setAttribute("inert", "");
  } else if (typeof sidebar.removeAttribute === "function") {
    sidebar.removeAttribute("inert");
  } else if (sidebar.attributes) {
    delete sidebar.attributes.inert;
  }
  if ("inert" in sidebar) {
    sidebar.inert = isInert;
  }
}

export function setSessionSidebarOpen(nextIsOpen, options = {}) {
  if (!appShell || !sidebarToggle) {
    return;
  }

  let isOpen = Boolean(nextIsOpen);
  // 桌面端保持侧栏可用，避免折叠后设置/新建等入口全部失效
  if (!compactSessionSidebarQuery.matches) {
    isOpen = true;
  }

  const shouldPersist = options.persist !== false;
  appShell.classList.toggle("sidebar-collapsed", !isOpen);
  appShell.classList.toggle("sidebar-open", isOpen);
  sidebarToggle.setAttribute("aria-expanded", String(isOpen));
  sidebarToggle.setAttribute("aria-label", isOpen ? "关闭侧栏" : "打开侧栏");

  if (sidebar) {
    sidebar.setAttribute("aria-hidden", String(!isOpen));
    if (compactSessionSidebarQuery.matches) {
      setSidebarInert(!isOpen);
    } else {
      setSidebarInert(false);
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
