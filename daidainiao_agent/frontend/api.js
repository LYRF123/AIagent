import { getCurrentSessionId, setCurrentSessionId } from "./state.js";
import { renderSessions, setSessionItems, renderSessionsFetchError } from "./render/sessions.js";

export class ApiError extends Error {
  constructor(message, { status = 0, code = "", requestId = "", detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.detail = detail;
  }
}

function detailToText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.message || item?.detail || String(item))
      .filter(Boolean)
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    return detail.message || detail.detail || detail.error || "";
  }
  return "";
}

async function readResponseBody(response) {
  if (typeof response.text === "function") {
    const raw = await response.text();
    try {
      return { raw, data: raw ? JSON.parse(raw) : {} };
    } catch {
      return { raw, data: {} };
    }
  }
  if (typeof response.json === "function") {
    try {
      const data = await response.json();
      return { raw: "", data: data || {} };
    } catch {
      return { raw: "", data: {} };
    }
  }
  return { raw: "", data: {} };
}

function responseHeader(response, name) {
  if (!response?.headers) return "";
  if (typeof response.headers.get === "function") return response.headers.get(name) || "";
  return response.headers[name] || response.headers[name.toLowerCase()] || "";
}

export async function parseApiError(response, fallback = "请求失败") {
  const { raw, data } = await readResponseBody(response);
  const requestId = data.request_id || responseHeader(response, "X-Request-ID");
  const detailText = detailToText(data.detail);
  const status = response.status || 0;
  const message = data.message || data.error || detailText || (raw && !raw.startsWith("{") ? raw.trim().slice(0, 240) : "") || `${fallback}${status ? `（HTTP ${status}）` : ""}`;
  return new ApiError(message, {
    status,
    code: data.error || data.code || "",
    requestId,
    detail: data.detail ?? data,
  });
}

async function parseJsonResponse(response, fallback) {
  const { raw, data } = await readResponseBody(response);
  if (!response.ok) {
    throw await parseApiError({
      status: response.status || 0,
      headers: response.headers,
      text: async () => raw,
      json: async () => data,
    }, fallback);
  }
  return data;
}

async function requestJson(url, { method = "GET", body } = {}, fallback = "请求失败") {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  return parseJsonResponse(response, fallback);
}

export async function refreshSessions(nextSessionId = getCurrentSessionId()) {
  try {
    const data = await requestJson("/sessions", {}, "刷新会话列表失败");
    const items = data.items || [];
    if (items.some((item) => item.session_id === nextSessionId)) {
      setCurrentSessionId(nextSessionId);
    } else if (!items.some((item) => item.session_id === getCurrentSessionId())) {
      setCurrentSessionId("");
    }
    setSessionItems(items);
  } catch (error) {
    console.warn("刷新会话列表失败:", error);
    renderSessionsFetchError();
  }
}

export async function loadSession(sessionId) {
  try {
    const data = await requestJson(`/sessions/${encodeURIComponent(sessionId)}`, {}, "加载会话失败");
    setCurrentSessionId(sessionId);
    await refreshSessions(sessionId);
    return { messages: data.messages || data.history || [], session_id: data.session_id || sessionId };
  } catch (error) {
    throw error;
  }
}

export async function createSession() {
  try {
    const data = await requestJson("/sessions", {
      method: "POST",
      body: {},
    }, "新建会话失败");
    setCurrentSessionId(data.session.session_id);
    renderSessions(data.sessions || []);
    return data.session;
  } catch (error) {
    throw error;
  }
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/import-document", {
    method: "POST",
    body: formData,
  });
  return parseJsonResponse(response, "导入失败");
}

export async function listDocuments() {
  return requestJson("/documents", {}, "读取文档列表失败");
}

export async function deleteDocument(paperId) {
  return requestJson("/delete-document", {
    method: "POST",
    body: { paper_id: paperId },
  }, "删除文档失败");
}

export async function listKnowledgeDocuments({ includeBase = true } = {}) {
  return requestJson(`/knowledge-documents?include_base=${includeBase ? "true" : "false"}`, {}, "读取知识库失败");
}

export async function getDocumentDetail(paperId, { passageLimit = 12 } = {}) {
  return requestJson(`/documents/${encodeURIComponent(paperId)}?passage_limit=${encodeURIComponent(String(passageLimit))}`, {}, "读取文档详情失败");
}

export async function getDocumentBrief(paperId) {
  return requestJson(`/documents/${encodeURIComponent(paperId)}/brief`, {}, "生成阅读摘要失败");
}

export async function exportMarkdown(data, format = "markdown") {
  return requestJson("/export/markdown", {
    method: "POST",
    body: { data, format },
  }, "导出失败");
}

export async function runRagLab(payload = {}) {
  return requestJson("/rag-lab/evaluate", {
    method: "POST",
    body: payload,
  }, "RAG Lab 运行失败");
}

export async function runDeepReview(payload = {}) {
  return requestJson("/deep-review", {
    method: "POST",
    body: payload,
  }, "生成综述失败");
}

export async function getRuntimeStatus() {
  return requestJson("/status", {}, "读取运行状态失败");
}

export async function getModelSettings() {
  return requestJson("/settings/model", {}, "读取模型设置失败");
}

export async function updateModelSettings(payload) {
  return requestJson("/settings/model", {
    method: "POST",
    body: payload,
  }, "更新模型设置失败");
}

export async function listAvailableModels(payload) {
  return requestJson("/settings/models/list", {
    method: "POST",
    body: payload,
  }, "获取模型列表失败");
}

export async function deleteSession(sessionId) {
  try {
    const data = await requestJson("/delete-session", {
      method: "POST",
      body: { session_id: sessionId },
    }, "删除会话失败");
    if (getCurrentSessionId() === sessionId) {
      setCurrentSessionId("");
    }
    renderSessions(data.sessions || []);
  } catch (error) {
    throw error;
  }
}

export async function truncateSession(sessionId, messageIndex) {
  try {
    const data = await requestJson(`/sessions/${encodeURIComponent(sessionId)}/truncate`, {
      method: "POST",
      body: { message_index: messageIndex },
    }, "截断会话失败");
    renderSessions(data.sessions || []);
    return data.session;
  } catch (error) {
    throw error;
  }
}
