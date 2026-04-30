import { statusPill, summaryOutput, detailOutput, jsonOutput } from "../state.js";
import {
  escapeHtml,
  formatTimestamp,
  formatScoreValue,
  formatFieldValue,
  hasValue,
  isPlainObject,
} from "./escape.js";

export function setStatus(text, kind = "idle") {
  statusPill.textContent = text;
  statusPill.className = `status-pill ${kind}`;
}

export function renderEmptySummary(title, text) {
  summaryOutput.innerHTML = `
    <div class="empty-state">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

export function renderList(title, items) {
  const rows = (items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `
    <section>
      <h4>${escapeHtml(title)}</h4>
      <ul>${rows || "<li>\u65E0</li>"}</ul>
    </section>
  `;
}

export function renderHistory(history) {
  if (!history || history.length === 0) {
    return `<div class="detail-block"><h4>\u4F1A\u8BDD\u5386\u53F2</h4><p class="block-note">\u5F53\u524D\u6CA1\u6709\u4FDD\u5B58\u7684\u4F1A\u8BDD\u5386\u53F2\u3002</p></div>`;
  }
  const rows = history.map((item) => `
    <div class="message-item ${escapeHtml(item.role)}">
      <div class="message-role">${item.role === "user" ? "\u7528\u6237" : "\u52A9\u624B"}</div>
      <p>${escapeHtml(item.content || "")}</p>
    </div>
  `).join("");
  return `<div class="detail-block"><h4>\u4F1A\u8BDD\u5386\u53F2</h4><div class="message-list">${rows}</div></div>`;
}

export function renderSessionPanel(session) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>${escapeHtml(session.title || "\u65B0\u4F1A\u8BDD")}</h3>
      <p class="summary-main">\u5171 ${escapeHtml(session.turn_count || 0)} \u8F6E\u95EE\u7B54</p>
      <p class="summary-meta">\u66F4\u65B0\u65F6\u95F4\uFF1A${escapeHtml(formatTimestamp(session.updated_at || ""))}</p>
    </div>
    <div class="summary-block">
      <h3>\u4F7F\u7528\u65B9\u5F0F</h3>
      <p class="summary-subtext">\u7EE7\u7EED\u5728\u5F53\u524D\u6A21\u5F0F\u91CC\u63D0\u95EE\uFF0C\u65B0\u7ED3\u679C\u4F1A\u81EA\u52A8\u8FFD\u52A0\u5230\u8FD9\u4E2A\u4F1A\u8BDD\u3002</p>
    </div>
  `;
  detailOutput.innerHTML = `
    ${renderHistory(session.messages)}
    <div class="detail-block">
      <h4>\u5F53\u524D\u9650\u5236</h4>
      <p class="block-note">\u5386\u53F2\u4F1A\u8BDD\u53EA\u4FDD\u5B58\u6D88\u606F\u5185\u5BB9\uFF1B\u8BC1\u636E\u7247\u6BB5\u548C\u8C03\u7528\u8F68\u8FF9\u4F1A\u5728\u65B0\u7684\u95EE\u7B54\u7ED3\u679C\u91CC\u5C55\u793A\u3002</p>
    </div>
  `;
  jsonOutput.textContent = JSON.stringify(session, null, 2);
}

export function renderStreamingAskState(answer, sessionTitle = "\u65B0\u4F1A\u8BDD") {
  const visibleAnswer = answer || "\u6B63\u5728\u751F\u6210\u56DE\u7B54...";
  const existingCursor = summaryOutput.querySelector(".streaming-cursor");

  if (existingCursor) {
    // Incremental update: only replace text before cursor
    const mainEl = summaryOutput.querySelector(".summary-main");
    if (mainEl) {
      // Remove old text nodes and cursor, rebuild
      mainEl.textContent = "";
      mainEl.append(visibleAnswer);
      mainEl.appendChild(existingCursor);
    }
    const metaEl = summaryOutput.querySelector(".summary-meta");
    if (metaEl) {
      metaEl.textContent = `\u4F1A\u8BDD\u6807\u9898\uFF1A${sessionTitle || "\u65B0\u4F1A\u8BDD"}`;
    }
  } else {
    // First call: set up full structure
    summaryOutput.innerHTML = `
      <div class="summary-block primary">
        <h3>\u56DE\u7B54\u751F\u6210\u4E2D</h3>
        <p class="summary-main">${escapeHtml(visibleAnswer)}<span class="streaming-cursor" aria-hidden="true"></span></p>
        <p class="summary-meta">\u4F1A\u8BDD\u6807\u9898\uFF1A${escapeHtml(sessionTitle || "\u65B0\u4F1A\u8BDD")}</p>
      </div>
      <div class="summary-block">
        <h3>\u6D41\u5F0F\u8F93\u51FA</h3>
        <p class="summary-subtext">\u56DE\u7B54\u6B63\u5728\u9010\u6BB5\u8FD4\u56DE\uFF1B\u6700\u7EC8\u8BC1\u636E\u3001\u8F68\u8FF9\u548C\u5B8C\u6574 JSON \u4F1A\u5728\u751F\u6210\u7ED3\u675F\u540E\u8865\u9F50\u3002</p>
      </div>
    `;
    detailOutput.innerHTML = `
      <div class="detail-block skeleton-block">
        <div class="skeleton-line"></div>
        <div class="skeleton-line skeleton-line-short"></div>
        <div class="skeleton-line skeleton-line-mid"></div>
      </div>
    `;
  }
}

export function renderMetricCards(entries) {
  if (!entries || entries.length === 0) {
    return `<p class="empty-note">\u540E\u7AEF\u8FD8\u6CA1\u6709\u8FD4\u56DE\u6C47\u603B\u6307\u6807\u3002</p>`;
  }
  return `
    <div class="metric-grid">
      ${entries.slice(0, 12).map(([name, value]) => `
        <div class="metric-card">
          <span>${escapeHtml(name)}</span>
          <strong>${escapeHtml(formatScoreValue(value) || formatFieldValue(value))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

export function renderKeyValuePills(item, excludeKeys = []) {
  if (!isPlainObject(item)) {
    return "";
  }
  const excluded = new Set(excludeKeys);
  const rows = Object.entries(item)
    .filter(([key, value]) => (
      !excluded.has(key)
      && !isPlainObject(value)
      && !Array.isArray(value)
      && hasValue(value)
    ))
    .slice(0, 10)
    .map(([key, value]) => `
      <span class="kv-pill">
        <span>${escapeHtml(key)}</span>
        ${escapeHtml(formatScoreValue(value) || formatFieldValue(value))}
      </span>
    `)
    .join("");
  return rows ? `<div class="kv-list">${rows}</div>` : "";
}
