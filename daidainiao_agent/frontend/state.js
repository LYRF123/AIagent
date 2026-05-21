// Session / submission state
let _currentSessionId = "";
let _isSubmitting = false;
const DEFAULT_SETTINGS = {
  topK: 5,
  strictGrounded: true,
  useRerank: true,
  modelProvider: "",
  modelApiKey: "",
  modelBaseUrl: "",
  modelName: "",
  activeProfileId: "",
  modelProfiles: [],
};

export function getCurrentSessionId() { return _currentSessionId; }
export function setCurrentSessionId(val) { _currentSessionId = val; }
export function getIsSubmitting() { return _isSubmitting; }
export function setIsSubmitting(val) { _isSubmitting = val; }

// Sidebar
export const sessionSidebarStorageKey = "daidainiao-agent-session-sidebar-open";
export const compactSessionSidebarQuery = window.matchMedia("(max-width: 768px)");

// DOM references
export const appShell = document.querySelector(".app-shell");
export const sidebar = document.getElementById("sidebar");
export const sidebarToggle = document.getElementById("sidebar-toggle");
export const sessionsOutput = document.getElementById("sessions-output");
export const newChatButton = document.getElementById("new-chat");
export const clearChatButton = document.getElementById("clear-chat");
export const settingsButton = document.getElementById("settings-button");
export const workspaceToggle = document.getElementById("workspace-toggle");
export const workspacePanel = document.getElementById("workspace-panel");
export const workspaceClose = document.getElementById("workspace-close");
export const chatMessages = document.getElementById("chat-messages");
export const welcomeScreen = document.getElementById("welcome-screen");
export const chatForm = document.getElementById("chat-form");
export const chatInput = document.getElementById("chat-input");
export const chatSubmit = document.getElementById("chat-submit");
export const chatStop = document.getElementById("chat-stop");

// Draft persistence
const DRAFT_KEY = "daidainiao-agent-draft";
const SETTINGS_KEY = "daidainiao-agent-settings";

function normalizeSettings(value = {}) {
  const parsedTopK = Number(value.topK);
  const topK = Number.isFinite(parsedTopK)
    ? Math.min(8, Math.max(1, Math.round(parsedTopK)))
    : DEFAULT_SETTINGS.topK;
  return {
    topK,
    strictGrounded: value.strictGrounded !== false,
    useRerank: value.useRerank !== false,
    modelProvider: value.modelProvider || DEFAULT_SETTINGS.modelProvider,
    modelApiKey: value.modelApiKey || DEFAULT_SETTINGS.modelApiKey,
    modelBaseUrl: String(value.modelBaseUrl || value.baseUrl || DEFAULT_SETTINGS.modelBaseUrl).trim(),
    modelName: String(value.modelName || value.model || DEFAULT_SETTINGS.modelName).trim(),
    activeProfileId: String(value.activeProfileId || "").trim(),
    modelProfiles: Array.isArray(value.modelProfiles) ? value.modelProfiles : DEFAULT_SETTINGS.modelProfiles,
  };
}

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

export function loadSettings() {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    return normalizeSettings(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings) {
  const normalized = normalizeSettings(settings);
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
  } catch {
    // ignore
  }
  return normalized;
}
