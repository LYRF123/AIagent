import { escapeHtml, renderSimpleMarkdown, getItemTitle, getItemText, truncateText, renderEvidenceMeta } from "./escape.js";
import { chatMessages, welcomeScreen } from "../state.js";

const THINKING_STEPS = [
  { key: "retrieve", label: "检索相关片段", note: "从候选内容里找线索" },
  { key: "decompose", label: "拆解问题", note: "确认问题重点" },
  { key: "generate", label: "组织回答", note: "生成简洁答案" },
  { key: "cite", label: "筛选引用片段", note: "整理最相关证据" },
];

const THINKING_HTML = `
<div class="chat-thinking">
  <button type="button" class="thinking-toggle" aria-expanded="false">
    <span class="thinking-label">正在思考…</span>
    <span class="thinking-progress">步骤 1 / ${THINKING_STEPS.length}</span>
    <svg class="thinking-toggle-chevron" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
  </button>
  <div class="thinking-inline-bar"><div class="thinking-bar-fill"></div></div>
  <div class="thinking-body">
    <ol class="thinking-steps">
      ${THINKING_STEPS.map((step, index) => `
        <li class="step" data-step="${step.key}" data-index="${index + 1}">
          <span class="step-dot" aria-hidden="true"></span>
          <span>
            <strong>${step.label}</strong>
            <small>${step.note}</small>
          </span>
        </li>
      `).join("")}
    </ol>
  </div>
</div>`;

function bindThinkingToggle(thinkingEl) {
  if (!thinkingEl || thinkingEl.dataset.boundToggle === "true") return;
  thinkingEl.dataset.boundToggle = "true";
  const toggle = thinkingEl.querySelector(".thinking-toggle");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const expanded = thinkingEl.classList.toggle("is-expanded");
    toggle.setAttribute("aria-expanded", String(expanded));
  });
}

export function appendUserMessage(text) {
  const html = `<div class="chat-msg chat-msg-user">
    <div class="chat-msg-user-actions">
      <button type="button" class="chat-msg-action-btn" data-action="edit" title="编辑">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M11.013 1.427a1.75 1.75 0 012.474 2.474L4.81 12.578a1 1 0 01-.413.242l-2.75.917a.25.25 0 01-.316-.316l.917-2.75a1 1 0 01.242-.413L11.013 1.427z" fill="currentColor"/></svg>
        编辑
      </button>
      <button type="button" class="chat-msg-action-btn" data-action="retry" title="重试">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M1.5 8A6.5 6.5 0 118 14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M1 5v3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        重试
      </button>
    </div>
    <p>${escapeHtml(text)}</p>
  </div>`;
  chatMessages.insertAdjacentHTML("beforeend", html);
  return chatMessages.lastElementChild;
}

export function appendAssistantMessage({ showThinking = true } = {}) {
  const html = `<div class="chat-msg chat-msg-assistant">${showThinking ? THINKING_HTML : ""}<div class="chat-answer"></div></div>`;
  chatMessages.insertAdjacentHTML("beforeend", html);
  const el = chatMessages.lastElementChild;
  const thinkingEl = el.querySelector(".chat-thinking");
  if (thinkingEl) bindThinkingToggle(thinkingEl);
  return {
    el,
    answerEl: el.querySelector(".chat-answer"),
    thinkingEl,
  };
}

export function updateThinkingSteps(el, { activeStep, doneSteps }) {
  if (!el) return;
  const steps = el.querySelectorAll(".step");
  let activeIndex = 1;
  steps.forEach((step) => {
    const name = step.dataset.step;
    step.classList.remove("active", "done");
    if (doneSteps && doneSteps.includes(name)) {
      step.classList.add("done");
    } else if (name === activeStep) {
      step.classList.add("active");
      activeIndex = Number(step.dataset.index || 1);
    }
  });
  const progress = el.querySelector(".thinking-progress");
  const finishedCount = Math.min(doneSteps?.length || 0, THINKING_STEPS.length);
  const visibleStep = activeStep ? activeIndex : Math.max(1, finishedCount);
  if (progress) {
    progress.textContent = `步骤 ${visibleStep} / ${THINKING_STEPS.length}`;
  }
  const bar = el.querySelector(".thinking-bar-fill");
  if (bar) {
    const total = THINKING_STEPS.length;
    const activeAdd = activeStep ? 0.5 : 0;
    const pct = Math.min(100, ((finishedCount + activeAdd) / total) * 100);
    bar.style.width = `${pct}%`;
  }
}

export function hideThinking(el) {
  if (!el) return;

  const steps = el.querySelectorAll(".step");
  steps.forEach((step) => {
    step.classList.remove("active");
    step.classList.add("done");
  });

  const bar = el.querySelector(".thinking-bar-fill");
  if (bar) bar.style.width = "100%";

  const progress = el.querySelector(".thinking-progress");
  if (progress) progress.textContent = "完成";

  el.classList.add("thinking-complete");

  setTimeout(() => {
    el.classList.add("thinking-fade-out");
    el.addEventListener("transitionend", function handler(e) {
      if (e.propertyName === "opacity") {
        el.style.display = "none";
        el.removeEventListener("transitionend", handler);
      }
    });
    setTimeout(() => {
      el.style.display = "none";
    }, 350);
  }, 450);
}

export function appendStreamDelta(el, delta) {
  const answerEl = el.querySelector(".chat-answer") || el;
  answerEl.insertAdjacentHTML("beforeend", escapeHtml(delta));
  answerEl.classList.add("streaming-cursor");
}

function buildExportActionsHtml() {
  return `
    <div class="answer-export-actions">
      <button type="button" class="ghost-button compact-button answer-export-copy" data-action="copy-markdown">复制 Markdown</button>
      <button type="button" class="ghost-button compact-button answer-export-download" data-action="download-markdown">下载 .md</button>
      <button type="button" class="ghost-button compact-button answer-export-obsidian" data-action="export-obsidian">Obsidian</button>
      <button type="button" class="ghost-button compact-button answer-export-bibtex" data-action="export-bibtex">BibTeX</button>
    </div>
  `;
}

export function bindAnswerExportActions(el, data) {
  const copyBtn = el.querySelector(".answer-export-copy");
  const downloadBtn = el.querySelector(".answer-export-download");
  const obsidianBtn = el.querySelector(".answer-export-obsidian");
  const bibtexBtn = el.querySelector(".answer-export-bibtex");
  if (!copyBtn || !downloadBtn) return;

  const runExport = async (format = "markdown") => {
    const { exportMarkdown } = await import("../api.js");
    return exportMarkdown(data, format);
  };

  copyBtn.addEventListener("click", async () => {
    try {
      const result = await runExport("markdown");
      await navigator.clipboard.writeText(result.markdown || "");
      copyBtn.textContent = "已复制";
      setTimeout(() => {
        copyBtn.textContent = "复制 Markdown";
      }, 1600);
    } catch (error) {
      copyBtn.textContent = "复制失败";
    }
  });

  downloadBtn.addEventListener("click", async () => {
    try {
      const result = await runExport("markdown");
      downloadBlob(result.markdown || "", result.filename || "answer.md", "text/markdown");
    } catch (error) {
      downloadBtn.textContent = "下载失败";
    }
  });

  obsidianBtn?.addEventListener("click", async () => {
    try {
      const result = await runExport("obsidian");
      downloadBlob(result.markdown || "", result.filename || "answer.md", "text/markdown");
    } catch {
      obsidianBtn.textContent = "失败";
    }
  });

  bibtexBtn?.addEventListener("click", async () => {
    try {
      const result = await runExport("bibtex");
      downloadBlob(result.markdown || "", result.filename || "refs.bib", "application/x-bibtex");
    } catch {
      bibtexBtn.textContent = "失败";
    }
  });
}

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function renderFinalAnswer(el, data) {
  const answerEl = el.querySelector(".chat-answer") || el;
  const evidenceCount = data.evidence ? data.evidence.length : 0;
  answerEl.innerHTML = renderSimpleMarkdown(data.answer, evidenceCount, data.evidence || []) + buildExportActionsHtml();
  answerEl.classList.remove("streaming-cursor");
  renderRetrievalDiagnostics(el, data.diagnostics);
  bindCitationClicks(el);
  bindAnswerExportActions(el, data);
}

function formatStageName(value) {
  const labels = {
    query_expansion: "扩展",
    tfidf: "TF-IDF",
    bm25: "BM25",
    vector: "向量",
    fusion: "融合",
    rerank: "重排",
    final_rank: "排序",
  };
  return labels[value] || value || "阶段";
}

function formatLatency(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}s`;
  return `${Math.round(numeric)}ms`;
}

function renderRetrievalDiagnostics(el, diagnostics) {
  const existing = el.querySelector(".retrieval-diagnostics");
  if (existing) existing.remove();
  if (!diagnostics || !Array.isArray(diagnostics.pipeline_stages) || diagnostics.pipeline_stages.length === 0) return;

  const stages = diagnostics.pipeline_stages;
  const completed = stages.filter((stage) => stage.status === "completed").length;
  const totalLatency = formatLatency(diagnostics.latency_ms);
  const method = diagnostics.fusion?.method || diagnostics.fusion_method || "hybrid";
  const html = `
    <details class="retrieval-diagnostics">
      <summary>
        <span>检索链路</span>
        <strong>${completed}/${stages.length} 完成 · ${escapeHtml(method)}${totalLatency ? ` · ${totalLatency}` : ""}</strong>
      </summary>
      <div class="retrieval-stage-list">
        ${stages.map((stage) => `
          <div class="retrieval-stage retrieval-stage-${escapeHtml(stage.status || "unknown")}">
            <span>${escapeHtml(formatStageName(stage.name))}</span>
            <strong>${escapeHtml(stage.status || "unknown")}</strong>
            ${formatLatency(stage.latency_ms) ? `<small>${escapeHtml(formatLatency(stage.latency_ms))}</small>` : ""}
          </div>
        `).join("")}
      </div>
    </details>
  `;
  const evidence = el.querySelector(".evidence-snippets");
  if (evidence) {
    evidence.insertAdjacentHTML("beforebegin", html);
  } else {
    el.insertAdjacentHTML("beforeend", html);
  }
}

function bindCitationClicks(el) {
  const chips = el.querySelectorAll("[data-citation-target]");
  chips.forEach((chip) => {
    if (chip.dataset.citationBound === "true") return;
    chip.dataset.citationBound = "true";
    chip.addEventListener("click", () => {
      const target = el.querySelector(`[data-evidence-index="${chip.dataset.citationTarget}"]`);
      if (!target) return;
      target.open = true;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("evidence-snippet-active");
      setTimeout(() => {
        target.classList.remove("evidence-snippet-active");
      }, 1400);
    });
  });
}

export function renderEvidenceSnippets(el, evidence) {
  if (!evidence || evidence.length === 0) return;
  const items = [...evidence];
  const html = items
    .map(
      (item, i) => `
    <details class="evidence-snippet" data-evidence-index="${i + 1}" data-paper-id="${escapeHtml(item.paper_id || "")}" data-page="${escapeHtml(item.page != null ? String(item.page) : "")}">
      <summary>
        <span>相关片段 ${i + 1}</span>
        <strong>${escapeHtml(truncateText(getItemTitle(item), 72))}</strong>
      </summary>
      ${renderEvidenceMeta(item, { includePaperId: false })}
      <p>${escapeHtml(truncateText(getItemText(item), 260))}</p>
      ${item.paper_id ? `<button type="button" class="ghost-button compact-button evidence-source-btn" data-paper-id="${escapeHtml(item.paper_id)}" data-page="${escapeHtml(item.page != null ? String(item.page) : "")}">查看来源</button>` : ""}
    </details>`
    )
    .join("");
  el.insertAdjacentHTML("beforeend", `<div class="evidence-snippets">${html}</div>`);
  bindCitationClicks(el);
  bindEvidenceSourceClicks(el);
}

function bindEvidenceSourceClicks(el) {
  el.querySelectorAll(".evidence-source-btn").forEach((button) => {
    if (button.dataset.boundSource === "true") return;
    button.dataset.boundSource = "true";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const paperId = button.dataset.paperId;
      const page = button.dataset.page || null;
      const snippet = button.closest(".evidence-snippet");
      const text = snippet?.querySelector("p")?.textContent || "";
      const { jumpToReadingSource } = await import("../workspace.js");
      await jumpToReadingSource({ paperId, page, highlightText: text });
      const { trackEvent } = await import("../analytics.js");
      trackEvent("evidence_source_click", { paper_id: paperId, page });
    });
  });
}

export function renderSessionHistory(messages) {
  if (!messages || messages.length === 0) return;
  messages.forEach((msg) => {
    if (msg.role === "user") {
      appendUserMessage(msg.content);
      return;
    }
    const { el } = appendAssistantMessage({ showThinking: false });
    const answerEl = el.querySelector(".chat-answer");
    const evidenceCount = msg.evidence ? msg.evidence.length : 0;
    answerEl.innerHTML = renderSimpleMarkdown(msg.content, evidenceCount, msg.evidence || []) + buildExportActionsHtml();
    renderRetrievalDiagnostics(el, msg.diagnostics);
    if (msg.evidence && msg.evidence.length > 0) {
      renderEvidenceSnippets(el, msg.evidence);
    }
    bindCitationClicks(el);
    bindAnswerExportActions(el, {
      answer: msg.content,
      evidence: msg.evidence || [],
      diagnostics: msg.diagnostics || null,
    });
  });
}

export function bindUserMessageActions(onRetry) {
  if (!chatMessages) return;
  chatMessages.addEventListener("click", (event) => {
    const btn = event.target.closest(".chat-msg-action-btn");
    if (!btn) return;
    const action = btn.dataset.action;
    const msgEl = btn.closest(".chat-msg-user");
    if (!msgEl) return;

    const p = msgEl.querySelector("p");
    const ta = msgEl.querySelector("textarea");

    if (action === "retry") {
      const text = p?.textContent?.trim() || "";
      if (!text) return;
      // Find the index of this user message
      const userMsgs = Array.from(chatMessages.querySelectorAll(".chat-msg-user"));
      const index = userMsgs.indexOf(msgEl);
      onRetry(text, index, false);
    } else if (action === "edit") {
      if (msgEl.classList.contains("is-editing")) return;
      const text = p?.textContent?.trim() || "";
      msgEl.classList.add("is-editing");

      // Replace p with textarea
      const newTa = document.createElement("textarea");
      newTa.className = "chat-msg-edit-input";
      newTa.value = text;
      newTa.dataset.original = text;
      newTa.rows = Math.min(8, text.split("\n").length + 1);
      p.replaceWith(newTa);
      newTa.focus();
      newTa.selectionStart = newTa.selectionEnd = newTa.value.length;

      // Update actions to confirm/cancel
      const actions = msgEl.querySelector(".chat-msg-user-actions");
      actions.innerHTML = `
        <button type="button" class="chat-msg-action-btn chat-msg-action-confirm" data-action="confirm" title="发送">发送</button>
        <button type="button" class="chat-msg-action-btn" data-action="cancel" title="取消">取消</button>
      `;

      // Keydown on textarea
      newTa.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          const confirmBtn = msgEl.querySelector('[data-action="confirm"]');
          confirmBtn?.click();
        }
        if (e.key === "Escape") {
          const cancelBtn = msgEl.querySelector('[data-action="cancel"]');
          cancelBtn?.click();
        }
      });
    } else if (action === "cancel") {
      if (!msgEl.classList.contains("is-editing")) return;
      msgEl.classList.remove("is-editing");

      const originalText = ta?.dataset.original || "";
      const newP = document.createElement("p");
      newP.textContent = originalText;
      ta.replaceWith(newP);

      // Restore actions
      const actions = msgEl.querySelector(".chat-msg-user-actions");
      actions.innerHTML = `
        <button type="button" class="chat-msg-action-btn" data-action="edit" title="编辑">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M11.013 1.427a1.75 1.75 0 012.474 2.474L4.81 12.578a1 1 0 01-.413.242l-2.75.917a.25.25 0 01-.316-.316l.917-2.75a1 1 0 01.242-.413L11.013 1.427z" fill="currentColor"/></svg>
          编辑
        </button>
        <button type="button" class="chat-msg-action-btn" data-action="retry" title="重试">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M1.5 8A6.5 6.5 0 118 14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M1 5v3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          重试
        </button>
      `;
    } else if (action === "confirm") {
      if (!msgEl.classList.contains("is-editing")) return;
      const newText = ta?.value?.trim() || "";
      if (!newText) return;

      msgEl.classList.remove("is-editing");
      const newP = document.createElement("p");
      newP.textContent = newText;
      ta.replaceWith(newP);

      // Restore actions
      const actions = msgEl.querySelector(".chat-msg-user-actions");
      actions.innerHTML = `
        <button type="button" class="chat-msg-action-btn" data-action="edit" title="编辑">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M11.013 1.427a1.75 1.75 0 012.474 2.474L4.81 12.578a1 1 0 01-.413.242l-2.75.917a.25.25 0 01-.316-.316l.917-2.75a1 1 0 01.242-.413L11.013 1.427z" fill="currentColor"/></svg>
          编辑
        </button>
        <button type="button" class="chat-msg-action-btn" data-action="retry" title="重试">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M1.5 8A6.5 6.5 0 118 14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M1 5v3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          重试
        </button>
      `;

      const userMsgs = Array.from(chatMessages.querySelectorAll(".chat-msg-user"));
      const index = userMsgs.indexOf(msgEl);
      onRetry(newText, index, true);
    }
  });
}

export function toggleWelcomeScreen(visible) {
  if (!welcomeScreen) return;
  welcomeScreen.classList.toggle("is-hidden", !visible);
  welcomeScreen.hidden = !visible;
}

export function scrollToBottom({ smooth = false } = {}) {
  if (!chatMessages) return;
  const top = chatMessages.scrollHeight;
  if (smooth && typeof chatMessages.scrollTo === "function") {
    chatMessages.scrollTo({ top, behavior: "smooth" });
    return;
  }
  chatMessages.scrollTop = top;
}

export function clearStreamError(el) {
  el?.querySelector?.(".chat-stream-error")?.remove();
}

export function showStreamError(el, { message, hint = "", retryLabel = "重试", requestId = "" } = {}) {
  if (!el) return null;
  const answerEl = el.querySelector(".chat-answer") || el;
  answerEl.classList.remove("streaming-cursor");
  clearStreamError(el);
  const safeMessage = escapeHtml(message || "请求失败，请稍后重试");
  const safeHint = hint ? `<p class="chat-stream-error-hint">${escapeHtml(hint)}</p>` : "";
  const safeRequestId = requestId ? `<code class="chat-stream-request-id">${escapeHtml(requestId)}</code>` : "";
  const wrapper = document.createElement("div");
  wrapper.className = "chat-stream-error";
  wrapper.setAttribute("role", "alert");
  wrapper.innerHTML = `
    <div class="chat-stream-error-body">
      <strong>${safeMessage}</strong>
      ${safeHint}
      ${safeRequestId}
    </div>
    <button type="button" class="ghost-button compact-button chat-stream-retry">${escapeHtml(retryLabel)}</button>
  `;
  answerEl.insertAdjacentElement("afterend", wrapper);
  return wrapper.querySelector(".chat-stream-retry");
}
