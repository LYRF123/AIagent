import { chatMessages, welcomeScreen } from "./state.js";
import { appendUserMessage, appendAssistantMessage, renderFinalAnswer, renderEvidenceSnippets, toggleWelcomeScreen } from "./render/chat.js";
import { setLastFinalPayload } from "./final-payload.js";
import { trackEvent } from "./analytics.js";

const DEMO_URL = "/static/data/demo_session.json";

export async function loadDemoSession() {
  const response = await fetch(DEMO_URL);
  if (!response.ok) {
    throw new Error("无法加载示例对话");
  }
  const data = await response.json();
  renderDemoSession(data);
  trackEvent("demo_session_loaded");
  return data;
}

export function renderDemoSession(data) {
  if (!chatMessages || !data) return;
  Array.from(chatMessages.children).forEach((child) => {
    if (child !== welcomeScreen) child.remove();
  });
  toggleWelcomeScreen(false);
  appendUserMessage(data.question || "示例问题");
  const { el } = appendAssistantMessage({ showThinking: false });
  const payload = { ...data, question: data.question || "" };
  renderFinalAnswer(el, payload);
  if (Array.isArray(data.evidence) && data.evidence.length) {
    renderEvidenceSnippets(el, data.evidence);
  }
  setLastFinalPayload(payload);
}
