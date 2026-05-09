import {
  appShell, sidebar, sidebarToggle,
  sessionsOutput, newChatButton, clearChatButton,
  settingsButton,
  chatMessages, welcomeScreen, chatForm, chatInput, chatSubmit,
  getCurrentSessionId, setCurrentSessionId,
  getIsSubmitting, setIsSubmitting,
  compactSessionSidebarQuery,
  saveDraft, loadDraft, clearDraft,
} from "./state.js";

import { refreshSessions, loadSession, createSession, deleteSession, uploadDocument, listDocuments } from "./api.js";
import { runChatStream } from "./stream.js";
import {
  toggleWelcomeScreen, scrollToBottom, renderSessionHistory,
} from "./render/chat.js";

import {
  shouldStartWithSessionSidebarOpen, setSessionSidebarOpen,
  getStoredSessionSidebarState, closeSessionSidebarOnSmallScreen,
} from "./handlers/sidebar.js";

if (chatForm) {
  chatForm.setAttribute("action", "javascript:void(0)");
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;
  if (getIsSubmitting()) return;

  setIsSubmitting(true);
  chatSubmit.disabled = true;
  clearDraft();

  try {
    await runChatStream({
      question,
      top_k: 3,
      session_id: getCurrentSessionId() || undefined,
      strict_grounded: true,
    });
  } finally {
    setIsSubmitting(false);
    chatSubmit.disabled = false;
    chatInput.value = "";
    chatInput.focus();
  }
}

// ── 1. 表单提交 ──────────────────────────────────────────────
chatForm.addEventListener("submit", submitQuestion);
chatSubmit.addEventListener("click", submitQuestion);

// ── 2. Textarea 自动增高 ────────────────────────────────────
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + "px";
});

// ── 3. Enter 提交 / Shift+Enter 换行 ─────────────────────────
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

// ── 4. 草稿自动保存 ─────────────────────────────────────────
let draftTimer = null;
chatInput.addEventListener("input", () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    saveDraft(chatInput.value);
  }, 300);
});

// ── 5. 新对话按钮 ───────────────────────────────────────────
newChatButton.addEventListener("click", async () => {
  toggleWelcomeScreen(true);
  for (const child of [...chatMessages.children]) {
    if (child !== welcomeScreen) child.remove();
  }
  await createSession();
  closeSessionSidebarOnSmallScreen();
  chatInput.focus();
});

// ── 6. 清空对话按钮 ─────────────────────────────────────────
clearChatButton.addEventListener("click", async () => {
  const sessionToDelete = getCurrentSessionId();
  if (sessionToDelete) {
    if (!window.confirm("确认清空当前对话吗？历史消息会一起清空。")) return;
  }
  // 先清空 UI
  toggleWelcomeScreen(true);
  for (const child of [...chatMessages.children]) {
    if (child !== welcomeScreen) child.remove();
  }
  chatInput.focus();
  // 再异步清理后端（不阻塞 UI）
  if (sessionToDelete) {
    try { await deleteSession(sessionToDelete); } catch { /* ignore */ }
  }
});

// ── 上传文档 ─────────────────────────────────────────────────
const uploadDocButton = document.getElementById("upload-doc-button");
const uploadFileInput = document.getElementById("upload-file-input");

if (uploadDocButton && uploadFileInput) {
  uploadDocButton.addEventListener("click", () => {
    uploadFileInput.click();
    closeSessionSidebarOnSmallScreen();
  });

  uploadFileInput.addEventListener("change", async () => {
    const file = uploadFileInput.files[0];
    if (!file) return;

    const validTypes = [".pdf", ".docx", ".txt"];
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!validTypes.includes(ext)) {
      window.alert("仅支持 PDF、DOCX、TXT 格式");
      uploadFileInput.value = "";
      return;
    }

    uploadDocButton.disabled = true;
    uploadDocButton.textContent = "导入中...";
    try {
      const result = await uploadDocument(file);
      window.alert(`已导入: ${result.filename}，当前共 ${result.documents.length} 篇文档`);
      uploadFileInput.value = "";
    } catch (err) {
      window.alert("导入失败: " + (err.message || "未知错误"));
    } finally {
      uploadDocButton.disabled = false;
      uploadDocButton.innerHTML = '<span aria-hidden="true">📄</span> 导入文档';
    }
  });
}

if (settingsButton) {
  settingsButton.addEventListener("click", () => {
    window.alert("设置稍后开放。");
    closeSessionSidebarOnSmallScreen();
  });
}

// ── 7. 侧栏切换 ─────────────────────────────────────────────
sidebarToggle.addEventListener("click", () => {
  const nextIsOpen = appShell.classList.contains("sidebar-collapsed");
  setSessionSidebarOpen(nextIsOpen);
});

// ── 8. 会话列表点击委托 ─────────────────────────────────────
sessionsOutput.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.classList.contains("session-open")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    toggleWelcomeScreen(false);
    for (const child of [...chatMessages.children]) {
      if (child !== welcomeScreen) child.remove();
    }
    const data = await loadSession(sessionId);
    renderSessionHistory(data.messages);
    scrollToBottom();
    closeSessionSidebarOnSmallScreen();
    return;
  }

  if (button.classList.contains("delete-session")) return;
});

// ── 9. 键盘快捷键 ───────────────────────────────────────────
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (compactSessionSidebarQuery.matches && appShell.classList.contains("sidebar-collapsed") === false) {
      setSessionSidebarOpen(false);
    }
    return;
  }

  if (!event.altKey) return;
  const tag = document.activeElement?.tagName;
  if (tag === "TEXTAREA" || (tag === "INPUT" && document.activeElement.type !== "checkbox")) {
    return;
  }

  if (event.key === "n" || event.key === "N") {
    event.preventDefault();
    newChatButton.click();
    return;
  }
  if (event.key === "s" || event.key === "S") {
    event.preventDefault();
    sidebarToggle.click();
    return;
  }
});

// ── 10. 移动端左滑关闭侧栏手势 ──────────────────────────────
const SWIPE_THRESHOLD = 80;

function addSwipeListener(el, direction, callback) {
  if (!el) return;
  let startX = 0;
  let startY = 0;
  let tracking = false;

  el.addEventListener("touchstart", (e) => {
    const touch = e.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    tracking = true;
  }, { passive: true });

  el.addEventListener("touchmove", (e) => {
    if (!tracking) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    if (Math.abs(dy) > Math.abs(dx)) {
      tracking = false;
    }
  }, { passive: true });

  el.addEventListener("touchend", (e) => {
    if (!tracking) return;
    tracking = false;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - startX;
    if (direction === "right" && dx > SWIPE_THRESHOLD) {
      callback();
    }
    if (direction === "left" && dx < -SWIPE_THRESHOLD) {
      callback();
    }
  }, { passive: true });
}

addSwipeListener(sidebar, "left", () => {
  if (compactSessionSidebarQuery.matches) {
    setSessionSidebarOpen(false);
  }
});

// ── 11. 响应式 media query 监听 ─────────────────────────────
if (compactSessionSidebarQuery.addEventListener) {
  compactSessionSidebarQuery.addEventListener("change", () => {
    if (getStoredSessionSidebarState() === null) {
      setSessionSidebarOpen(!compactSessionSidebarQuery.matches, { persist: false });
    }
  });
}

// ── 12. 初始化 ──────────────────────────────────────────────
setSessionSidebarOpen(shouldStartWithSessionSidebarOpen(), { persist: false });
const draft = loadDraft();
if (draft) {
  chatInput.value = draft;
}
toggleWelcomeScreen(true);
refreshSessions();

window.__DODO_CHAT_READY = true;
