// Session / submission state
let _currentSessionId = "";
let _isSubmitting = false;

export function getCurrentSessionId() { return _currentSessionId; }
export function setCurrentSessionId(val) { _currentSessionId = val; }
export function getIsSubmitting() { return _isSubmitting; }
export function setIsSubmitting(val) { _isSubmitting = val; }

// Sidebar
export const sessionSidebarStorageKey = "research-agent-session-sidebar-open";
export const compactSessionSidebarQuery = window.matchMedia("(max-width: 768px)");

// DOM references
export const appShell = document.querySelector(".app-shell");
export const sidebar = document.getElementById("sidebar");
export const sidebarToggle = document.getElementById("sidebar-toggle");
export const sessionsOutput = document.getElementById("sessions-output");
export const newChatButton = document.getElementById("new-chat");
export const clearChatButton = document.getElementById("clear-chat");
export const settingsButton = document.getElementById("settings-button");
export const chatMessages = document.getElementById("chat-messages");
export const welcomeScreen = document.getElementById("welcome-screen");
export const chatForm = document.getElementById("chat-form");
export const chatInput = document.getElementById("chat-input");
export const chatSubmit = document.getElementById("chat-submit");

// Draft persistence
const DRAFT_KEY = "research-agent-draft";

export function saveDraft(text) {
  try {
    window.localStorage.setItem(DRAFT_KEY, text);
  } catch {
    // ignore
  }
}

export function loadDraft() {
  try {
    return window.localStorage.getItem(DRAFT_KEY) || "";
  } catch {
    return "";
  }
}

export function clearDraft() {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {
    // ignore
  }
}
