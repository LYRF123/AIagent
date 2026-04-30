import { documentsOutput } from "../state.js";
import { escapeHtml } from "./escape.js";
import { deleteDocument } from "../api.js";

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

  document.querySelectorAll(".delete-document").forEach((button) => {
    button.addEventListener("click", async () => {
      const paperId = button.dataset.paperId;
      if (!paperId) {
        return;
      }
      if (!window.confirm("\u786E\u8BA4\u5220\u9664\u8FD9\u4EFD\u6587\u6863\u5417\uFF1F\u5220\u9664\u540E\u4F1A\u540C\u6B65\u5237\u65B0\u77E5\u8BC6\u5E93\u7D22\u5F15\u3002")) {
        return;
      }
      await deleteDocument(paperId);
    });
  });
}
