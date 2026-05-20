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
  <div class="thinking-head">
    <span class="thinking-label">正在思考<span class="dot dot1">.</span><span class="dot dot2">.</span><span class="dot dot3">.</span></span>
    <span class="thinking-progress">步骤 1 / ${THINKING_STEPS.length}</span>
  </div>
  <div class="thinking-bar"><div class="thinking-bar-fill"></div></div>
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
</div>`;

export function appendUserMessage(text) {
  const html = `<div class="chat-msg chat-msg-user"><p>${escapeHtml(text)}</p></div>`;
  chatMessages.insertAdjacentHTML("beforeend", html);
  return chatMessages.lastElementChild;
}

export function appendAssistantMessage({ showThinking = true } = {}) {
  const html = `<div class="chat-msg chat-msg-assistant">${showThinking ? THINKING_HTML : ""}<div class="chat-answer"></div></div>`;
  chatMessages.insertAdjacentHTML("beforeend", html);
  const el = chatMessages.lastElementChild;
  return {
    el,
    answerEl: el.querySelector(".chat-answer"),
    thinkingEl: el.querySelector(".chat-thinking"),
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

export function renderFinalAnswer(el, data) {
  const answerEl = el.querySelector(".chat-answer") || el;
  const evidenceCount = data.evidence ? data.evidence.length : 0;
  answerEl.innerHTML = renderSimpleMarkdown(data.answer, evidenceCount, data.evidence || []);
  answerEl.classList.remove("streaming-cursor");
  renderRetrievalDiagnostics(el, data.diagnostics);
  bindCitationClicks(el);
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
    <details class="evidence-snippet" data-evidence-index="${i + 1}">
      <summary>
        <span>相关片段 ${i + 1}</span>
        <strong>${escapeHtml(truncateText(getItemTitle(item), 72))}</strong>
      </summary>
      ${renderEvidenceMeta(item, { includePaperId: false })}
      <p>${escapeHtml(truncateText(getItemText(item), 260))}</p>
    </details>`
    )
    .join("");
  el.insertAdjacentHTML("beforeend", `<div class="evidence-snippets">${html}</div>`);
  bindCitationClicks(el);
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
    answerEl.innerHTML = renderSimpleMarkdown(msg.content, evidenceCount, msg.evidence || []);
    renderRetrievalDiagnostics(el, msg.diagnostics);
    if (msg.evidence && msg.evidence.length > 0) {
      renderEvidenceSnippets(el, msg.evidence);
    }
    bindCitationClicks(el);
  });
}

export function toggleWelcomeScreen(visible) {
  if (welcomeScreen) {
    welcomeScreen.style.display = visible ? "" : "none";
  }
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

export function showStreamError(el, { message, hint = "", retryLabel = "重试" } = {}) {
  if (!el) return null;
  const answerEl = el.querySelector(".chat-answer") || el;
  answerEl.classList.remove("streaming-cursor");
  clearStreamError(el);
  const safeMessage = escapeHtml(message || "请求失败，请稍后重试");
  const safeHint = hint ? `<p class="chat-stream-error-hint">${escapeHtml(hint)}</p>` : "";
  const wrapper = document.createElement("div");
  wrapper.className = "chat-stream-error";
  wrapper.setAttribute("role", "alert");
  wrapper.innerHTML = `
    <div class="chat-stream-error-body">
      <strong>${safeMessage}</strong>
      ${safeHint}
    </div>
    <button type="button" class="ghost-button compact-button chat-stream-retry">${escapeHtml(retryLabel)}</button>
  `;
  answerEl.insertAdjacentElement("afterend", wrapper);
  return wrapper.querySelector(".chat-stream-retry");
}
