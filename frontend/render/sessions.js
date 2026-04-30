import { sessionsOutput, getCurrentSessionId } from "../state.js";
import { escapeHtml, formatTimestamp } from "./escape.js";
import { loadSession, deleteSession } from "../api.js";
import { closeSessionSidebarOnSmallScreen } from "../handlers/sidebar.js";

export function renderSessions(items) {
  if (!items || items.length === 0) {
    sessionsOutput.innerHTML = `<p class="empty-note">\u8FD8\u6CA1\u6709\u4F1A\u8BDD\u3002</p>`;
    return;
  }

  sessionsOutput.innerHTML = items.map((item) => `
    <div class="session-card ${item.session_id === getCurrentSessionId() ? "active" : ""}">
      <button class="session-open" data-session-id="${escapeHtml(item.session_id)}" type="button">
        <strong>${escapeHtml(item.title || "\u65B0\u4F1A\u8BDD")}</strong>
        <p class="block-note">${escapeHtml(item.preview || "\u8FD8\u6CA1\u6709\u5386\u53F2\u6D88\u606F\u3002")}</p>
        <p class="session-meta">${escapeHtml(`${item.turn_count || 0} \u8F6E \u00B7 ${formatTimestamp(item.updated_at || "")}`)}</p>
      </button>
      <button class="danger-button compact-button delete-session" data-session-id="${escapeHtml(item.session_id)}" type="button">\u5220\u9664</button>
    </div>
  `).join("");

  document.querySelectorAll(".session-open").forEach((button) => {
    button.addEventListener("click", async () => {
      const sessionId = button.dataset.sessionId;
      if (!sessionId) {
        return;
      }
      await loadSession(sessionId);
      closeSessionSidebarOnSmallScreen();
    });
  });

  document.querySelectorAll(".delete-session").forEach((button) => {
    button.addEventListener("click", async () => {
      const sessionId = button.dataset.sessionId;
      if (!sessionId) {
        return;
      }
      if (!window.confirm("\u786E\u8BA4\u5220\u9664\u8FD9\u4E2A\u4F1A\u8BDD\u5417\uFF1F\u5386\u53F2\u6D88\u606F\u4F1A\u4E00\u8D77\u6E05\u7A7A\u3002")) {
        return;
      }
      await deleteSession(sessionId);
    });
  });
}
