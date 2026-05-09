import { getCurrentSessionId, setCurrentSessionId } from "./state.js";
import { refreshSessions } from "./api.js";
import {
  appendUserMessage,
  appendAssistantMessage,
  updateThinkingSteps,
  hideThinking,
  appendStreamDelta,
  renderFinalAnswer,
  renderEvidenceSnippets,
  scrollToBottom,
  toggleWelcomeScreen,
} from "./render/chat.js";

let activeController = null;

export async function readEventStream(response, onEvent) {
  if (!response.body) {
    throw new Error("\u5F53\u524D\u6D4F\u89C8\u5668\u4E0D\u652F\u6301\u6D41\u5F0F\u54CD\u5E94\u8BFB\u53D6\u3002");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  function processBlock(block) {
    if (!block.trim()) {
      return;
    }
    let eventType = "message";
    const dataLines = [];
    block.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    });
    const rawData = dataLines.join("\n");
    const parsed = rawData ? JSON.parse(rawData) : {};
    onEvent(eventType, parsed);
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      processBlock(block);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      if (buffer.trim()) {
        processBlock(buffer);
      }
      break;
    }
  }
}

export async function runChatStream(payload) {
  if (activeController) {
    activeController.abort();
  }
  const controller = new AbortController();
  activeController = controller;

  toggleWelcomeScreen(false);
  appendUserMessage(payload.question);
  const { el, answerEl, thinkingEl } = appendAssistantMessage();
  scrollToBottom();

  let stepTimer = null;
  const doneSteps = [];
  stepTimer = setTimeout(() => {
    updateThinkingSteps(thinkingEl, { activeStep: "retrieve", doneSteps });
    stepTimer = setTimeout(() => {
      doneSteps.push("retrieve");
      updateThinkingSteps(thinkingEl, { activeStep: "decompose", doneSteps });
      stepTimer = setTimeout(() => {
        doneSteps.push("decompose");
        updateThinkingSteps(thinkingEl, { activeStep: "generate", doneSteps });
      }, 800);
    }, 800);
  }, 0);

  const markCiteStep = () => {
    clearTimeout(stepTimer);
    updateThinkingSteps(thinkingEl, {
      activeStep: "cite",
      doneSteps: ["retrieve", "decompose", "generate"],
    });
  };

  try {
    const response = await fetch("/ask-stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || `\u8BF7\u6C42\u5931\u8D25\uFF1A${response.status}`);
    }

    let finalPayload = null;
    let handledError = false;

    await readEventStream(response, (eventType, data) => {
      if (eventType === "chunk") {
        clearTimeout(stepTimer);
        updateThinkingSteps(thinkingEl, { activeStep: "generate", doneSteps: ["retrieve", "decompose"] });
        appendStreamDelta(el, data.delta);
        scrollToBottom();
        return;
      }
      if (eventType === "session") {
        setCurrentSessionId(data.session_id || getCurrentSessionId());
        return;
      }
      if (eventType === "final") {
        markCiteStep();
        finalPayload = data;
        return;
      }
      if (eventType === "error") {
        handledError = true;
        clearTimeout(stepTimer);
        hideThinking(thinkingEl);
        answerEl.textContent = `错误：${data.error || "流式输出失败"}`;
        answerEl.style.color = "var(--danger)";
        scrollToBottom();
      }
    });

    if (handledError) {
      return;
    }
    if (!finalPayload) {
      throw new Error("\u6D41\u5F0F\u8BF7\u6C42\u63D0\u524D\u7ED3\u675F\uFF0C\u672A\u6536\u5230\u6700\u7EC8\u7ED3\u679C\u3002");
    }

    markCiteStep();

    setTimeout(async () => {
      hideThinking(thinkingEl);
      renderFinalAnswer(el, finalPayload);
      if (Array.isArray(finalPayload.evidence)) {
        renderEvidenceSnippets(el, finalPayload.evidence);
      }
      scrollToBottom();
      if (finalPayload.session_id) {
        setCurrentSessionId(finalPayload.session_id);
        await refreshSessions(finalPayload.session_id);
      }
    }, 50);
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    clearTimeout(stepTimer);
    hideThinking(thinkingEl);
    answerEl.textContent = `错误：${error.message || "未知错误"}`;
    answerEl.style.color = "var(--danger)";
    scrollToBottom();
  } finally {
    clearTimeout(stepTimer);
    if (activeController === controller) {
      activeController = null;
    }
  }
}
