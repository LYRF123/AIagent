import {
  getCurrentSessionId,
  setCurrentSessionId,
  summaryOutput,
  detailOutput,
  jsonOutput,
  sessionsOutput,
  documentsOutput,
} from "./state.js";
import { escapeHtml } from "./render/escape.js";
import { setStatus, renderEmptySummary, renderSessionPanel } from "./render/common.js";
import { renderSessions } from "./render/sessions.js";
import { renderDocuments } from "./render/documents.js";
import { openUtilityDrawer } from "./handlers/utility.js";

export async function refreshDocuments() {
  try {
    const response = await fetch("/documents");
    const data = await response.json();
    renderDocuments(data.items || []);
  } catch {
    documentsOutput.innerHTML = `<p class="empty-note">\u6587\u6863\u5217\u8868\u52A0\u8F7D\u5931\u8D25\u3002</p>`;
  }
}

export async function refreshSessions(nextSessionId = getCurrentSessionId()) {
  try {
    const response = await fetch("/sessions");
    const data = await response.json();
    const items = data.items || [];
    if (items.some((item) => item.session_id === nextSessionId)) {
      setCurrentSessionId(nextSessionId);
    } else if (!items.some((item) => item.session_id === getCurrentSessionId())) {
      setCurrentSessionId("");
    }
    renderSessions(items);
  } catch {
    sessionsOutput.innerHTML = `<p class="empty-note">\u4F1A\u8BDD\u5217\u8868\u52A0\u8F7D\u5931\u8D25\u3002</p>`;
  }
}

export async function loadSession(sessionId) {
  setStatus("\u6B63\u5728\u52A0\u8F7D\u4F1A\u8BDD...", "loading");
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `\u52A0\u8F7D\u5931\u8D25\uFF1A${response.status}`);
    }
    setCurrentSessionId(sessionId);
    renderSessionPanel(data);
    await refreshSessions(sessionId);
    setStatus("\u4F1A\u8BDD\u5DF2\u52A0\u8F7D", "success");
  } catch (error) {
    setStatus("\u4F1A\u8BDD\u52A0\u8F7D\u5931\u8D25", "error");
    renderEmptySummary("\u4F1A\u8BDD\u52A0\u8F7D\u5931\u8D25", error.message || "\u65E0\u6CD5\u8BFB\u53D6\u4F1A\u8BDD\u8BE6\u60C5");
    detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u5237\u65B0\u4F1A\u8BDD\u5217\u8868\u540E\u91CD\u8BD5\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

export async function createSession() {
  setStatus("\u6B63\u5728\u521B\u5EFA\u4F1A\u8BDD...", "loading");
  try {
    const response = await fetch("/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `\u521B\u5EFA\u5931\u8D25\uFF1A${response.status}`);
    }
    setCurrentSessionId(data.session.session_id);
    renderSessionPanel(data.session);
    renderSessions(data.sessions || []);
    setStatus("\u5DF2\u521B\u5EFA\u65B0\u4F1A\u8BDD", "success");
  } catch (error) {
    setStatus("\u521B\u5EFA\u5931\u8D25", "error");
    renderEmptySummary("\u521B\u5EFA\u4F1A\u8BDD\u5931\u8D25", error.message || "\u4F1A\u8BDD\u521B\u5EFA\u5931\u8D25");
    detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

export async function deleteSession(sessionId) {
  setStatus("\u6B63\u5728\u5220\u9664\u4F1A\u8BDD...", "loading");
  try {
    const response = await fetch("/delete-session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `\u5220\u9664\u5931\u8D25\uFF1A${response.status}`);
    }
    if (getCurrentSessionId() === sessionId) {
      setCurrentSessionId("");
      renderEmptySummary("\u4F1A\u8BDD\u5DF2\u5220\u9664", "\u53EF\u4EE5\u65B0\u5EFA\u4F1A\u8BDD\uFF0C\u6216\u8005\u76F4\u63A5\u63D0\u95EE\u81EA\u52A8\u751F\u6210\u65B0\u7684\u4F1A\u8BDD\u3002");
      detailOutput.innerHTML = `<p class="empty-note">\u5F53\u524D\u6CA1\u6709\u9009\u4E2D\u7684\u4F1A\u8BDD\u3002</p>`;
      jsonOutput.textContent = JSON.stringify(data, null, 2);
    }
    renderSessions(data.sessions || []);
    setStatus("\u4F1A\u8BDD\u5DF2\u5220\u9664", "success");
  } catch (error) {
    setStatus("\u5220\u9664\u5931\u8D25", "error");
    renderEmptySummary("\u5220\u9664\u4F1A\u8BDD\u5931\u8D25", error.message || "\u4F1A\u8BDD\u5220\u9664\u5931\u8D25");
    detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

export async function importDocument(file) {
  const body = new FormData();
  body.append("file", file);
  setStatus("\u6B63\u5728\u5BFC\u5165\u6587\u4EF6...", "loading");
  const response = await fetch("/import-document", {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `\u5BFC\u5165\u5931\u8D25\uFF1A${response.status}`);
  }
  setStatus("\u5BFC\u5165\u5B8C\u6210", "success");
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>\u5BFC\u5165\u6210\u529F</h3>
      <p class="summary-main">${escapeHtml(data.document.title)}</p>
      <p class="summary-meta">paper_id: ${escapeHtml(data.document.paper_id)}</p>
    </div>
    <div class="summary-block">
      <h3>\u63A5\u4E0B\u6765\u53EF\u4EE5\u505A\u4EC0\u4E48</h3>
      <p class="summary-subtext">\u73B0\u5728\u4F60\u53EF\u4EE5\u76F4\u63A5\u5728 Ask \u91CC\u9488\u5BF9\u8FD9\u4EFD\u65B0\u6587\u6863\u63D0\u95EE\uFF0C\u6216\u7528 RAG Lab \u505A\u8BC4\u6D4B\u3002</p>
    </div>
  `;
  detailOutput.innerHTML = `
    <div class="detail-block">
      <h4>\u5BFC\u5165\u7ED3\u679C</h4>
      <p>${escapeHtml(data.message || "")}</p>
      <p class="block-note">\u5F53\u524D\u5DF2\u5BFC\u5165\u6587\u6863\u6570\uFF1A${escapeHtml(data.document.imported_count || 0)}</p>
      <p>${escapeHtml(data.document.summary_preview || "")}</p>
    </div>
  `;
  jsonOutput.textContent = JSON.stringify(data, null, 2);
  renderDocuments(data.documents || []);
  openUtilityDrawer("documents");
}

export async function deleteDocument(paperId) {
  setStatus("\u6B63\u5728\u5220\u9664\u6587\u6863...", "loading");
  try {
    const response = await fetch("/delete-document", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paper_id: paperId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `\u5220\u9664\u5931\u8D25\uFF1A${response.status}`);
    }
    setStatus("\u5220\u9664\u5B8C\u6210", "success");
    summaryOutput.innerHTML = `
      <div class="summary-block primary">
        <h3>\u5220\u9664\u6210\u529F</h3>
        <p class="summary-main">${escapeHtml(data.document.title)}</p>
        <p class="summary-meta">\u5269\u4F59\u6587\u6863\u6570\uFF1A${escapeHtml(data.document.remaining_count)}</p>
      </div>
    `;
    detailOutput.innerHTML = `
      <div class="detail-block">
        <h4>\u5220\u9664\u7ED3\u679C</h4>
        <p>${escapeHtml(data.message || "")}</p>
      </div>
    `;
    jsonOutput.textContent = JSON.stringify(data, null, 2);
    renderDocuments(data.documents || []);
    openUtilityDrawer("documents");
  } catch (error) {
    setStatus("\u5220\u9664\u5931\u8D25", "error");
    renderEmptySummary("\u5220\u9664\u5931\u8D25", error.message || "\u6587\u6863\u5220\u9664\u5931\u8D25");
    detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u5148\u5237\u65B0\u6587\u6863\u5217\u8868\u3002</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}
