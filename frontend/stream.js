import { jsonOutput, getCurrentSessionId, setCurrentSessionId } from "./state.js";
import { setStatus, renderStreamingAskState } from "./render/common.js";
import { renderAskSummary } from "./render/ask.js";
import { refreshSessions } from "./api.js";

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

export async function runAskModeStream(payload) {
  let sessionTitle = "\u65B0\u4F1A\u8BDD";
  let streamedAnswer = "";
  let finalPayload = null;
  let streamError = null;

  setStatus("\u6B63\u5728\u6D41\u5F0F\u751F\u6210\u56DE\u7B54...", "loading");
  renderStreamingAskState(streamedAnswer, sessionTitle);
  jsonOutput.textContent = JSON.stringify({ status: "streaming", question: payload.question }, null, 2);

  const response = await fetch("/ask-stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || `\u8BF7\u6C42\u5931\u8D25\uFF1A${response.status}`);
  }

  await readEventStream(response, (eventType, data) => {
    if (eventType === "session") {
      setCurrentSessionId(data.session_id || getCurrentSessionId());
      sessionTitle = data.session_title || sessionTitle;
      renderStreamingAskState(streamedAnswer, sessionTitle);
      return;
    }
    if (eventType === "chunk") {
      streamedAnswer += data.delta || "";
      renderStreamingAskState(streamedAnswer, sessionTitle);
      jsonOutput.textContent = JSON.stringify(
        {
          status: "streaming",
          session_id: getCurrentSessionId() || undefined,
          answer_preview: streamedAnswer,
        },
        null,
        2,
      );
      return;
    }
    if (eventType === "final") {
      finalPayload = data;
      return;
    }
    if (eventType === "error") {
      streamError = new Error(data.error || "\u6D41\u5F0F\u8F93\u51FA\u5931\u8D25");
    }
  });

  if (streamError) {
    throw streamError;
  }
  if (!finalPayload) {
    throw new Error("\u6D41\u5F0F\u8BF7\u6C42\u63D0\u524D\u7ED3\u675F\uFF0C\u672A\u6536\u5230\u6700\u7EC8\u7ED3\u679C\u3002");
  }

  setStatus("\u95EE\u7B54\u5B8C\u6210", "success");
  renderAskSummary(finalPayload);
  jsonOutput.textContent = JSON.stringify(finalPayload, null, 2);
  if (finalPayload.session_id) {
    setCurrentSessionId(finalPayload.session_id);
    await refreshSessions(finalPayload.session_id);
  }
}
