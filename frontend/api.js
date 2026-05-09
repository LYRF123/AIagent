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
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Upload failed: ${response.status}`);
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
