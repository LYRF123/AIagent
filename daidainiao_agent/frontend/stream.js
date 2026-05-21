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
  showStreamError,
  clearStreamError,
} from "./render/chat.js";

let activeController = null;
let lastFinalPayload = null;
let lastStreamQuestion = "";

export function getLastFinalPayload() {
  return lastFinalPayload;
}

export function isChatStreamActive() {
  return Boolean(activeController);
}

export function abortChatStream() {
  if (activeController) {
    activeController.abort();
  }
}

export async function readEventStream(response, onEvent) {
  if (!response.body) {
    throw new Error("当前浏览器不支持流式响应读取。");
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
    let parsed = {};
    if (rawData) {
      try {
        parsed = JSON.parse(rawData);
      } catch {
        throw new Error("流式数据格式异常，请重试。");
      }
    }
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

function hasPartialAnswer(answerEl) {
  return Boolean(answerEl?.textContent?.trim());
}

function publishStreamStatus(message) {
  const live = document.getElementById("chat-stream-status");
  if (live) live.textContent = message || "";
}

export async function runChatStream(payload, { onError, onAbort, onRetry } = {}) {
  if (activeController) {
    activeController.abort();
  }
  const controller = new AbortController();
  activeController = controller;
  lastStreamQuestion = payload.question || "";

  toggleWelcomeScreen(false);
  appendUserMessage(payload.question);
  const { el, answerEl, thinkingEl } = appendAssistantMessage();
  clearStreamError(el);
  scrollToBottom({ smooth: true });
  publishStreamStatus("正在连接并检索…");

  let stepTimer = null;
  const doneSteps = [];
  let firstChunkReceived = false;
  let usingSimulatedSteps = true;

  const applyPipelineStep = (stepName) => {
    if (!stepName || !thinkingEl) {
      return;
    }
    usingSimulatedSteps = false;
    clearTimeout(stepTimer);
    const order = ["retrieve", "decompose", "generate", "cite"];
    const index = order.indexOf(stepName);
    if (index < 0) {
      return;
    }
    const completed = order.slice(0, index);
    const active = index < order.length - 1 ? order[index] : "cite";
    updateThinkingSteps(thinkingEl, { activeStep: active, doneSteps: completed });
  };

  stepTimer = setTimeout(() => {
    if (!usingSimulatedSteps) {
      return;
    }
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

  const finishWithError = (message, hint = "") => {
    clearTimeout(stepTimer);
    hideThinking(thinkingEl);
    publishStreamStatus(message);
    const retryBtn = showStreamError(el, { message, hint });
    if (retryBtn && typeof onRetry === "function") {
      retryBtn.addEventListener("click", () => onRetry(), { once: true });
    }
    scrollToBottom({ smooth: true });
    if (typeof onError === "function") onError(message);
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
      let message = `请求失败：${response.status}`;
      try {
        const data = await response.json();
        message = data.error || message;
      } catch {
        // ignore parse errors
      }
      throw new Error(message);
    }

    let finalPayload = null;
    let handledError = false;

    await readEventStream(response, (eventType, data) => {
      if (eventType === "step") {
        applyPipelineStep(data.step);
        return;
      }
      if (eventType === "chunk") {
        clearTimeout(stepTimer);
        publishStreamStatus("正在生成回答…");
        if (!firstChunkReceived) {
          firstChunkReceived = true;
          if (usingSimulatedSteps) {
            updateThinkingSteps(thinkingEl, { activeStep: "decompose", doneSteps: ["retrieve"] });
            setTimeout(() => {
              updateThinkingSteps(thinkingEl, { activeStep: "generate", doneSteps: ["retrieve", "decompose"] });
            }, 250);
          }
        }
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
        lastFinalPayload = data;
        return;
      }
      if (eventType === "error") {
        handledError = true;
        finishWithError(data.error || "流式输出失败", "可检查模型配置或网络后重试。");
      }
    });

    if (handledError) {
      return;
    }
    if (!finalPayload) {
      throw new Error("连接已断开，未收到完整回答。");
    }

    markCiteStep();
    publishStreamStatus("正在整理引用…");

    await new Promise((resolve) => {
      setTimeout(resolve, 600);
    });

    hideThinking(thinkingEl);
    renderFinalAnswer(el, finalPayload);
    if (Array.isArray(finalPayload.evidence)) {
      renderEvidenceSnippets(el, finalPayload.evidence);
    }
    scrollToBottom({ smooth: true });
    publishStreamStatus("");
    if (finalPayload.session_id) {
      setCurrentSessionId(finalPayload.session_id);
      await refreshSessions(finalPayload.session_id);
    }
  } catch (error) {
    if (error.name === "AbortError") {
      clearTimeout(stepTimer);
      hideThinking(thinkingEl);
      const partial = hasPartialAnswer(answerEl);
      const message = partial ? "已停止生成" : "已取消请求";
      publishStreamStatus(message);
      if (!partial) {
        finishWithError(message, "你可以修改问题后重新发送。");
      } else {
        const note = document.createElement("p");
        note.className = "chat-stream-stopped-note";
        note.textContent = message;
        el.appendChild(note);
        scrollToBottom({ smooth: true });
      }
      if (typeof onAbort === "function") onAbort();
      return;
    }
    finishWithError(error.message || "未知错误", "请确认后端已启动，或稍后再试。");
  } finally {
    clearTimeout(stepTimer);
    if (activeController === controller) {
      activeController = null;
    }
    publishStreamStatus("");
  }
}

export function getLastStreamQuestion() {
  return lastStreamQuestion;
}
