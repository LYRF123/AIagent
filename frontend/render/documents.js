import { documentsOutput } from "../state.js";
import { escapeHtml } from "./escape.js";

export function renderDocuments(items) {
  if (!items || items.length === 0) {
    documentsOutput.innerHTML = `<p class="empty-note">\u8FD8\u6CA1\u6709\u5BFC\u5165\u6587\u4EF6\u3002</p>`;
    return;
  }
  documentsOutput.innerHTML = items.map((item) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p class="block-note">paper_id: ${escapeHtml(item.paper_id)}</p>
        </div>
        <button class="danger-button compact-button delete-document" data-paper-id="${escapeHtml(item.paper_id)}" type="button">\u5220\u9664</button>
      </header>
      <p class="block-note">\u6587\u4EF6\uFF1A${escapeHtml(item.file_name || "")}</p>
      <p class="block-note">\u6765\u6E90\uFF1A${escapeHtml(item.source_url || "")}</p>
      <p>${escapeHtml(item.summary_preview || "")}</p>
    </div>
  `).join("");
}
