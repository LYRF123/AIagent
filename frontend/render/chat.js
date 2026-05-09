import { escapeHtml, renderSimpleMarkdown, getItemTitle, getItemText, truncateText, renderEvidenceMeta } from "./escape.js";
import { chatMessages, welcomeScreen } from "../state.js";

const THINKING_STEPS = [
  { key: "retrieve", label: "检索相关片段", note: "从候选内容里找线索" },
  { key: "decompose", label: "拆解问题", note: "确认问题重点" },
  { key: "generate", label: "组织回答", note: "生成简洁答案" },
  { key: "cite", label: "筛选引用片段", note: "保留 3 个最相关片段" },
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

export function appendAssistantMessage() {
  const html = `<div class="chat-msg chat-msg-assistant">${THINKING_HTML}<div class="chat-answer"></div></div>`;
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
  if (el) el.style.display = "none";
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
}

export function renderEvidenceSnippets(el, evidence) {
  if (!evidence || evidence.length === 0) return;
  const items = [...evidence]
    .sort((a, b) => {
      const left = Number(a?.score);
      const right = Number(b?.score);
      if (!Number.isFinite(left) && !Number.isFinite(right)) return 0;
      if (!Number.isFinite(left)) return 1;
      if (!Number.isFinite(right)) return -1;
      return right - left;
    })
    .slice(0, 3);
  const html = items
    .map(
      (item, i) => `
    <details class="evidence-snippet">
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
}

export function renderSessionHistory(messages) {
  if (!messages || messages.length === 0) return;
  messages.forEach((msg) => {
    if (msg.role === "user") {
      appendUserMessage(msg.content);
      return;
    }
    const { el, thinkingEl } = appendAssistantMessage();
    hideThinking(thinkingEl);
    const answerEl = el.querySelector(".chat-answer");
    const evidenceCount = msg.evidence ? msg.evidence.length : 0;
    answerEl.innerHTML = renderSimpleMarkdown(msg.content, evidenceCount, msg.evidence || []);
    if (msg.evidence && msg.evidence.length > 0) {
      renderEvidenceSnippets(el, msg.evidence);
    }
  });
}

export function toggleWelcomeScreen(visible) {
  if (welcomeScreen) {
    welcomeScreen.style.display = visible ? "" : "none";
  }
}

export function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}
