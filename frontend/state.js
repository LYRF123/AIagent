export const modeButtons = Array.from(document.querySelectorAll(".mode-button"));
export const modeFields = Array.from(document.querySelectorAll("#agent-form [data-mode]"));
export const presetButtons = Array.from(document.querySelectorAll(".preset-button"));
export const utilityNavButtons = Array.from(document.querySelectorAll("[data-utility-panel-target]"));
export const utilityPanels = Array.from(document.querySelectorAll("[data-utility-panel]"));
export const form = document.getElementById("agent-form");
export const uploadForm = document.getElementById("upload-form");
export const uploadFile = document.getElementById("upload-file");
export const refreshDocumentsButton = document.getElementById("refresh-documents");
export const submitButton = document.getElementById("submit-button");
export const healthButton = document.getElementById("health-button");
export const newSessionButton = document.getElementById("new-session");
export const openToolsButton = document.getElementById("open-tools");
export const closeUtilityButton = document.getElementById("close-utility");
export const strictGroundedInput = document.getElementById("strict-grounded");
export const useRagasInput = document.getElementById("use-ragas");
export const topKInput = document.getElementById("top-k");
export const candidateKInput = document.getElementById("candidate-k");
export const ragRerankInput = document.getElementById("rag-rerank");
export const ragCompareConfigsInput = document.getElementById("rag-compare-configs");
export const statusPill = document.getElementById("status-pill");
export const sessionsOutput = document.getElementById("sessions-output");
export const summaryOutput = document.getElementById("summary-output");
export const detailOutput = document.getElementById("detail-output");
export const documentsOutput = document.getElementById("documents-output");
export const jsonOutput = document.getElementById("json-output");
export const modeBadge = document.getElementById("mode-badge");
export const utilityDrawer = document.getElementById("utility-drawer");
export const utilityTitle = document.getElementById("utility-title");
export const appShell = document.querySelector(".app-shell");
export const sessionSidebar = document.getElementById("session-sidebar");
export const sessionSidebarToggle = document.getElementById("session-sidebar-toggle");

let _currentMode = "ask";
let _currentSessionId = "";
let _currentUtility = "presets";
let _isSubmitting = false;
let _activeEvidenceHighlightTimeout = 0;

export function getCurrentMode() { return _currentMode; }
export function setCurrentMode(val) { _currentMode = val; }
export function getCurrentSessionId() { return _currentSessionId; }
export function setCurrentSessionId(val) { _currentSessionId = val; }
export function getCurrentUtility() { return _currentUtility; }
export function setCurrentUtility(val) { _currentUtility = val; }
export function getIsSubmitting() { return _isSubmitting; }
export function setIsSubmitting(val) { _isSubmitting = val; }
export function getActiveEvidenceHighlightTimeout() { return _activeEvidenceHighlightTimeout; }
export function setActiveEvidenceHighlightTimeout(val) { _activeEvidenceHighlightTimeout = val; }

export const sessionSidebarStorageKey = "research-agent-session-sidebar-open";
export const compactSessionSidebarQuery = window.matchMedia("(max-width: 960px)");

export const modeLabels = {
  ask: "Ask",
  rag_lab: "RAG Lab",
  search: "\u68C0\u7D22",
  compare: "\u5BF9\u6BD4",
  review: "\u7EFC\u8FF0",
  evaluate: "\u8BC4\u6D4B",
};

export const submitLabels = {
  ask: "\u8FD0\u884C Ask",
  rag_lab: "\u8FD0\u884C RAG Lab",
};

export const sectionLabels = {
  summary: "\u6458\u8981",
  methods: "\u65B9\u6CD5",
  findings: "\u7ED3\u8BBA",
  limitations: "\u5C40\u9650",
  topics: "\u4E3B\u9898\u8BCD",
};

export const claimStatusLabels = {
  supported: "supported",
  weak: "weak",
  unsupported: "unsupported",
  citation_mismatch: "citation_mismatch",
};

export const utilityLabels = {
  presets: "\u5FEB\u6377\u793A\u4F8B",
  import: "\u6587\u6863\u5BFC\u5165",
  documents: "\u77E5\u8BC6\u5E93\u6587\u4EF6",
  json: "\u539F\u59CB JSON",
  usage: "API \u7528\u91CF",
};

export const ragFlightStageOrder = ["query_expansion", "tfidf", "bm25", "vector", "fusion", "rerank", "final"];
export const ragFlightStageLabels = {
  query_expansion: "query expansion",
  tfidf: "tfidf",
  bm25: "bm25",
  vector: "vector",
  fusion: "fusion",
  rerank: "rerank",
  final: "final",
};

const DRAFT_KEY = "research-agent-draft";

export function saveDraft(formData) {
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(formData));
  } catch {
    // ignore
  }
}

export function loadDraft() {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (raw) {
      return JSON.parse(raw);
    }
  } catch {
    // ignore
  }
  return null;
}

export function clearDraft() {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {
    // ignore
  }
}
