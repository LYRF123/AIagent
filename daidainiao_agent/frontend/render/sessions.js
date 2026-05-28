import { sessionsOutput, getCurrentSessionId } from "../state.js";
import { escapeHtml, formatTimestamp } from "./escape.js";

let _allSessions = [];
let _searchQuery = "";
let _fetchFailed = false;

function startOfDay(date) {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function isToday(isoValue) {
  if (!isoValue) return false;
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return startOfDay(date).getTime() === startOfDay(now).getTime();
}

function isYesterday(isoValue) {
  if (!isoValue) return false;
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return false;
  const yesterday = startOfDay(new Date());
  yesterday.setDate(yesterday.getDate() - 1);
  return startOfDay(date).getTime() === yesterday.getTime();
}

function isWithinDays(isoValue, days) {
  if (!isoValue) return false;
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return false;
  const cutoff = startOfDay(new Date());
  cutoff.setDate(cutoff.getDate() - days);
  return startOfDay(date).getTime() >= cutoff.getTime();
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
  _fetchFailed = false;
  renderSessionsFiltered();
}

export function renderSessionsFetchError() {
  _fetchFailed = true;
  if (!sessionsOutput) return;
  sessionsOutput.innerHTML = `
    <div class="session-fetch-error">
      <p class="empty-note">会话列表加载失败</p>
      <button id="sessions-retry" class="ghost-button compact-button" type="button">重试</button>
    </div>
  `;
}

export function getSessionTitleById(sessionId) {
  const item = _allSessions.find((entry) => entry.session_id === sessionId);
  return item?.title || "";
}

export function renderSessions(items) {
  setSessionItems(items);
}

function renderSessionsFiltered() {
  if (!sessionsOutput) return;
  if (_fetchFailed) {
    renderSessionsFetchError();
    return;
  }
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
  const yesterdayItems = filtered.filter((item) => isYesterday(item.updated_at));
  const weekItems = filtered.filter((item) => !isToday(item.updated_at) && !isYesterday(item.updated_at) && isWithinDays(item.updated_at, 7));
  const earlierItems = filtered.filter((item) => !isToday(item.updated_at) && !isYesterday(item.updated_at) && !isWithinDays(item.updated_at, 7));
  const groups = [
    renderSessionGroup("今天", todayItems),
    renderSessionGroup("昨天", yesterdayItems),
    renderSessionGroup("近 7 天", weekItems),
    renderSessionGroup("更早", earlierItems),
  ].filter(Boolean);
  sessionsOutput.innerHTML = groups.join("");
}
