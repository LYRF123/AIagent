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
  utilityDrawer,
  appShell,
  sessionSidebarToggle,
  compactSessionSidebarQuery,
} from "./state.js";

import { setStatus, renderEmptySummary } from "./render/common.js";
import { escapeHtml } from "./render/escape.js";
import { focusEvidenceCard } from "./render/evidence.js";
import { refreshDocuments, refreshSessions, createSession, importDocument } from "./api.js";

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
});

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
showMode(getCurrentMode());
showUtilityPanel(getCurrentUtility());
closeUtilityDrawer();
refreshDocuments();
refreshSessions();
