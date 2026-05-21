import { getCurrentSessionId, setCurrentSessionId } from "./state.js";
import { renderSessions } from "./render/sessions.js";

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
  } catch (error) {
    console.warn("刷新会话列表失败:", error);
  }
}

export async function loadSession(sessionId) {
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Load failed: ${response.status}`);
    }
    setCurrentSessionId(sessionId);
    await refreshSessions(sessionId);
    return { messages: data.messages || data.history || [], session_id: data.session_id || sessionId };
  } catch (error) {
    throw error;
  }
}

export async function createSession() {
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
      throw new Error(data.error || `Create failed: ${response.status}`);
    }
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
  let data = {};
  const raw = await response.text();
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = {};
  }
  if (!response.ok) {
    const detail = data.detail;
    const detailText = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg || d).join("; ") : "";
    const fallback = raw && !raw.startsWith("{") ? raw.trim().slice(0, 240) : "";
    throw new Error(data.error || detailText || fallback || `导入失败（HTTP ${response.status}），请重启后端服务后重试`);
  }
  return data;
}

export async function listDocuments() {
  const response = await fetch("/documents");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `List failed: ${response.status}`);
  }
  return data;
}

export async function deleteDocument(paperId) {
  const response = await fetch("/delete-document", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ paper_id: paperId }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Delete failed: ${response.status}`);
  }
  return data;
}

export async function listKnowledgeDocuments({ includeBase = true } = {}) {
  const response = await fetch(`/knowledge-documents?include_base=${includeBase ? "true" : "false"}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Knowledge list failed: ${response.status}`);
  }
  return data;
}

export async function getDocumentDetail(paperId, { passageLimit = 12 } = {}) {
  const response = await fetch(`/documents/${encodeURIComponent(paperId)}?passage_limit=${encodeURIComponent(String(passageLimit))}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Document detail failed: ${response.status}`);
  }
  return data;
}

export async function getDocumentBrief(paperId) {
  const response = await fetch(`/documents/${encodeURIComponent(paperId)}/brief`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Document brief failed: ${response.status}`);
  }
  return data;
}

export async function runRagLab(payload = {}) {
  const response = await fetch("/rag-lab/evaluate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `RAG Lab failed: ${response.status}`);
  }
  return data;
}

export async function runDeepReview(payload = {}) {
  const response = await fetch("/deep-review", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Review failed: ${response.status}`);
  }
  return data;
}

export async function getRuntimeStatus() {
  const response = await fetch("/status");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Status failed: ${response.status}`);
  }
  return data;
}

export async function getModelSettings() {
  const response = await fetch("/settings/model");
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Model settings failed: ${response.status}`);
  }
  return data;
}

export async function updateModelSettings(payload) {
  const response = await fetch("/settings/model", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Model settings update failed: ${response.status}`);
  }
  return data;
}

export async function listAvailableModels(payload) {
  const response = await fetch("/settings/models/list", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Model list failed: ${response.status}`);
  }
  return data;
}

export async function deleteSession(sessionId) {
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
      throw new Error(data.error || `Delete failed: ${response.status}`);
    }
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
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}/truncate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message_index: messageIndex }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Truncate failed: ${response.status}`);
    }
    renderSessions(data.sessions || []);
    return data.session;
  } catch (error) {
    throw error;
  }
}
