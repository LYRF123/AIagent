import {
  getCurrentMode,
  getCurrentUtility,
  modeButtons,
  presetButtons,
  utilityNavButtons,
  form,
  uploadForm,
  uploadFile,
  refreshDocumentsButton,
  submitButton,
  healthButton,
  newSessionButton,
  openToolsButton,
  closeUtilityButton,
  summaryOutput,
  detailOutput,
  jsonOutput,
  sessionsOutput,
  documentsOutput,
  utilityDrawer,
  appShell,
  sessionSidebarToggle,
  compactSessionSidebarQuery,
  saveDraft,
  loadDraft,
  clearDraft,
} from "./state.js";

import { setStatus, renderEmptySummary } from "./render/common.js";
import { escapeHtml } from "./render/escape.js";
import { focusEvidenceCard } from "./render/evidence.js";
import { refreshDocuments, refreshSessions, createSession, importDocument, loadSession, deleteSession, deleteDocument } from "./api.js";

import { showMode, runMode, applyPreset } from "./handlers/mode.js";
import { showUtilityPanel, openUtilityDrawer, closeUtilityDrawer } from "./handlers/utility.js";
import {
  shouldStartWithSessionSidebarOpen,
  setSessionSidebarOpen,
  getStoredSessionSidebarState,
  closeSessionSidebarOnSmallScreen,
} from "./handlers/sidebar.js";

modeButtons.forEach((button) => {
  button.addEventListener("click", () => showMode(button.dataset.mode));
});

presetButtons.forEach((button) => {
  button.addEventListener("click", () => applyPreset(button.dataset.preset));
});

utilityNavButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.utilityPanelTarget;
    if (target) {
      showUtilityPanel(target);
    }
  });
});

if (openToolsButton) {
  openToolsButton.addEventListener("click", () => {
    if (utilityDrawer.classList.contains("hidden")) {
      openUtilityDrawer(getCurrentUtility() || "presets");
    } else {
      closeUtilityDrawer();
    }
  });
}

if (closeUtilityButton) {
  closeUtilityButton.addEventListener("click", () => {
    closeUtilityDrawer();
  });
}

summaryOutput.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const chip = target?.closest(".citation-chip");
  if (!chip) {
    return;
  }
  focusEvidenceCard(chip.dataset.citationTarget);
});

detailOutput.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const chip = target?.closest(".claim-audit-block .citation-chip");
  if (!chip) {
    return;
  }
  focusEvidenceCard(chip.dataset.citationTarget);
});

detailOutput.addEventListener("focusin", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const chip = target?.closest(".claim-audit-block .citation-chip");
  if (!chip) {
    return;
  }
  focusEvidenceCard(chip.dataset.citationTarget, { moveFocus: false });
});

sessionsOutput.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.classList.contains("session-open")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    await loadSession(sessionId);
    closeSessionSidebarOnSmallScreen();
    return;
  }

  if (button.classList.contains("delete-session")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    if (!window.confirm("\u786E\u8BA4\u5220\u9664\u8FD9\u4E2A\u4F1A\u8BDD\u5417\uFF1F\u5386\u53F2\u6D88\u606F\u4F1A\u4E00\u8D77\u6E05\u7A7A\u3002")) return;
    await deleteSession(sessionId);
  }
});

documentsOutput.addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-document");
  if (!button) return;
  const paperId = button.dataset.paperId;
  if (!paperId) return;
  if (!window.confirm("\u786E\u8BA4\u5220\u9664\u8FD9\u4EFD\u6587\u6863\u5417\uFF1F\u5220\u9664\u540E\u4F1A\u540C\u6B65\u5237\u65B0\u77E5\u8BC6\u5E93\u7D22\u5F15\u3002")) return;
  await deleteDocument(paperId);
});

if (sessionSidebarToggle) {
  sessionSidebarToggle.addEventListener("click", () => {
    const nextIsOpen = !appShell?.classList.contains("session-sidebar-open");
    setSessionSidebarOpen(nextIsOpen);
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (!utilityDrawer.classList.contains("hidden")) {
    closeUtilityDrawer();
  }
  if (compactSessionSidebarQuery.matches && appShell?.classList.contains("session-sidebar-open")) {
    setSessionSidebarOpen(false);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runMode(getCurrentMode());
  clearDraft();
});

let draftTimer = null;
form.addEventListener("input", () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    saveDraft({
      mode: getCurrentMode(),
      fields: {
        "ask-question": document.getElementById("ask-question")?.value || "",
        "search-query": document.getElementById("search-query")?.value || "",
        "compare-ids": document.getElementById("compare-ids")?.value || "",
        "compare-focus": document.getElementById("compare-focus")?.value || "",
        "review-topic": document.getElementById("review-topic")?.value || "",
        "candidate-k": document.getElementById("candidate-k")?.value || "20",
        "rag-rerank": document.getElementById("rag-rerank")?.checked || false,
        "rag-compare-configs": document.getElementById("rag-compare-configs")?.checked || true,
        "strict-grounded": document.getElementById("strict-grounded")?.checked || false,
        "use-ragas": document.getElementById("use-ragas")?.checked || false,
        "top-k": document.getElementById("top-k")?.value || "5",
      },
    });
  }, 300);
});

form.addEventListener("change", () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    saveDraft({
      mode: getCurrentMode(),
      fields: {
        "ask-question": document.getElementById("ask-question")?.value || "",
        "search-query": document.getElementById("search-query")?.value || "",
        "compare-ids": document.getElementById("compare-ids")?.value || "",
        "compare-focus": document.getElementById("compare-focus")?.value || "",
        "review-topic": document.getElementById("review-topic")?.value || "",
        "candidate-k": document.getElementById("candidate-k")?.value || "20",
        "rag-rerank": document.getElementById("rag-rerank")?.checked || false,
        "rag-compare-configs": document.getElementById("rag-compare-configs")?.checked || true,
        "strict-grounded": document.getElementById("strict-grounded")?.checked || false,
        "use-ragas": document.getElementById("use-ragas")?.checked || false,
        "top-k": document.getElementById("top-k")?.value || "5",
      },
    });
  }, 300);
});

function collectFormDataFromDraft(draft) {
  if (!draft || !draft.fields) return;
  for (const [id, value] of Object.entries(draft.fields)) {
    const el = document.getElementById(id);
    if (!el) continue;
    if (el.type === "checkbox") {
      el.checked = Boolean(value);
    } else {
      el.value = String(value);
    }
  }
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = uploadFile.files?.[0];
  if (!file) {
    setStatus("\u8BF7\u5148\u9009\u62E9\u6587\u4EF6", "error");
    return;
  }
  try {
    await importDocument(file);
    uploadForm.reset();
  } catch (error) {
    setStatus("\u5BFC\u5165\u5931\u8D25", "error");
    renderEmptySummary("\u5BFC\u5165\u5931\u8D25", error.message || "\u6587\u4EF6\u5BFC\u5165\u5931\u8D25");
    detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u786E\u8BA4\u6587\u4EF6\u683C\u5F0F\u4E3A PDF\u3001DOCX \u6216 TXT\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
});

if (refreshDocumentsButton) {
  refreshDocumentsButton.addEventListener("click", async () => {
    setStatus("\u6B63\u5728\u5237\u65B0\u6587\u6863\u5217\u8868...", "loading");
    await refreshDocuments();
    openUtilityDrawer("documents");
    setStatus("\u6587\u6863\u5217\u8868\u5DF2\u5237\u65B0", "success");
  });
}

if (newSessionButton) {
  newSessionButton.addEventListener("click", async () => {
    await createSession();
    closeSessionSidebarOnSmallScreen();
  });
}

healthButton.addEventListener("click", async () => {
  setStatus("\u6B63\u5728\u68C0\u67E5\u670D\u52A1...", "loading");
  try {
    const response = await fetch("/health");
    const data = await response.json();
    setStatus("\u670D\u52A1\u6B63\u5E38", "success");
    summaryOutput.innerHTML = `
      <div class="summary-block primary">
        <h3>\u5065\u5EB7\u68C0\u67E5</h3>
        <p class="summary-main">\u670D\u52A1\u53EF\u8BBF\u95EE\uFF0C\u72B6\u6001\u6B63\u5E38\u3002</p>
      </div>
    `;
    detailOutput.innerHTML = `<div class="detail-block"><h4>\u8FD4\u56DE\u5185\u5BB9</h4><p>${escapeHtml(JSON.stringify(data))}</p></div>`;
    jsonOutput.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    setStatus("\u5065\u5EB7\u68C0\u67E5\u5931\u8D25", "error");
    renderEmptySummary("\u670D\u52A1\u4E0D\u53EF\u7528", error.message || "\u8BF7\u68C0\u67E5\u672C\u5730\u670D\u52A1");
    detailOutput.innerHTML = `<p class="empty-note">\u5982\u679C\u670D\u52A1\u6CA1\u542F\u52A8\uFF0C\u8BF7\u91CD\u65B0\u8FD0\u884C research_agent.server\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
});

if (compactSessionSidebarQuery.addEventListener) {
  compactSessionSidebarQuery.addEventListener("change", () => {
    if (getStoredSessionSidebarState() === null) {
      setSessionSidebarOpen(!compactSessionSidebarQuery.matches, { persist: false });
    }
  });
}

setSessionSidebarOpen(shouldStartWithSessionSidebarOpen(), { persist: false });
const draft = loadDraft();
if (draft) {
  if (draft.mode) showMode(draft.mode);
  collectFormDataFromDraft(draft);
} else {
  showMode(getCurrentMode());
}
showUtilityPanel(getCurrentUtility());
closeUtilityDrawer();
refreshDocuments();
refreshSessions();
