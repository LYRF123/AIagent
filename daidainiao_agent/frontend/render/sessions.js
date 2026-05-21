import { sessionsOutput, getCurrentSessionId } from "../state.js";
import { escapeHtml, formatTimestamp } from "./escape.js";

let _allSessions = [];
let _searchQuery = "";

function isToday(isoValue) {
  if (!isoValue) return false;
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function filterSessions(items, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return items;
  return items.filter((item) => {
    const haystack = `${item.title || ""} ${item.preview || ""}`.toLowerCase();
    return haystack.includes(normalized);
  });
}

function renderSessionCard(item) {
  return `
    <div class="session-card ${item.session_id === getCurrentSessionId() ? "active" : ""}">
      <button class="session-open" data-session-id="${escapeHtml(item.session_id)}" type="button">
        <strong>${escapeHtml(item.title || "新会话")}</strong>
        <p class="block-note">${escapeHtml(item.preview || "还没有历史消息。")}</p>
        <p class="session-meta">${escapeHtml(`${item.turn_count || 0} 轮 · ${formatTimestamp(item.updated_at || "")}`)}</p>
      </button>
      <button class="delete-session" data-session-id="${escapeHtml(item.session_id)}" type="button" aria-label="删除会话" title="删除会话">&times;</button>
    </div>
  `;
}

function renderSessionGroup(title, items) {
  if (!items.length) return "";
  return `
    <div class="session-group">
      <p class="session-group-title">${escapeHtml(title)}</p>
      ${items.map((item) => renderSessionCard(item)).join("")}
    </div>
  `;
}

export function setSessionSearchQuery(query) {
  _searchQuery = query || "";
  renderSessionsFiltered();
}

export function setSessionItems(items) {
  _allSessions = Array.isArray(items) ? items : [];
  renderSessionsFiltered();
}

export function renderSessions(items) {
  setSessionItems(items);
}

function renderSessionsFiltered() {
  const filtered = filterSessions(_allSessions, _searchQuery);
  if (!_allSessions.length) {
    sessionsOutput.innerHTML = `<p class="empty-note">还没有会话。</p>`;
    return;
  }
  if (!filtered.length) {
    sessionsOutput.innerHTML = `<p class="empty-note">没有匹配的会话。</p>`;
    return;
  }
  const todayItems = filtered.filter((item) => isToday(item.updated_at));
  const earlierItems = filtered.filter((item) => !isToday(item.updated_at));
  const groups = [
    renderSessionGroup("今天", todayItems),
    renderSessionGroup("更早", earlierItems),
  ].filter(Boolean);
  sessionsOutput.innerHTML = groups.join("");
}
