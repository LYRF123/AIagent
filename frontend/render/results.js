import { summaryOutput, detailOutput } from "../state.js";
import {
  escapeHtml,
  hasValue,
  firstPresent,
  formatFieldValue,
  formatScoreValue,
  renderEvidenceMeta,
  getItemTitle,
  getItemText,
} from "./escape.js";
import { renderEmptySummary, renderList } from "./common.js";
import { renderHighlightList, renderTrace, renderRagasPanel } from "./evidence.js";
import { renderAskSummary } from "./ask.js";
import { renderRagLabSummary } from "./rag-lab.js";

export function renderSearchSummary(data) {
  if (!data || data.length === 0) {
    renderEmptySummary("\u6CA1\u6709\u68C0\u7D22\u7ED3\u679C", "\u53EF\u4EE5\u6362\u4E00\u4E2A\u66F4\u5177\u4F53\u7684\u5173\u952E\u8BCD\uFF0C\u6216\u8005\u628A Top K \u8C03\u5927\u4E00\u70B9\u3002");
    detailOutput.innerHTML = `<p class="empty-note">\u68C0\u7D22\u4E3A\u7A7A\u65F6\uFF0C\u8FD9\u91CC\u6CA1\u6709\u66F4\u591A\u7EC6\u8282\u3002</p>`;
    return;
  }

  const top = data[0];
  const topScore = formatScoreValue(firstPresent(top.score, top.relevance_score, top.similarity));
  const topPaperId = firstPresent(top.paper_id, top.document_id, top.doc_id);
  const topMetaParts = [];
  if (hasValue(topPaperId)) {
    topMetaParts.push(`paper_id: ${formatFieldValue(topPaperId)}`);
  }
  if (topScore) {
    topMetaParts.push(`\u5206\u6570 ${topScore}`);
  }
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>\u6700\u76F8\u5173\u7ED3\u679C</h3>
      <p class="summary-main">${escapeHtml(getItemTitle(top))}</p>
      ${topMetaParts.length ? `<p class="summary-meta">${escapeHtml(topMetaParts.join(" \u00B7 "))}</p>` : ""}
      ${renderEvidenceMeta(top, { includePaperId: false, className: "summary-evidence-meta" })}
    </div>
    <div class="summary-block">
      <h3>\u53EF\u5FEB\u901F\u9605\u8BFB\u7684\u4FE1\u606F</h3>
      <p class="summary-subtext">\u5148\u770B\u6807\u9898\u548C highlights\uFF0C\u518D\u51B3\u5B9A\u662F\u5426\u7EE7\u7EED\u95EE\u7B54\u6216\u505A\u5BF9\u6BD4\u3002</p>
    </div>
  `;

  const cards = data.map((item) => {
    const score = formatScoreValue(firstPresent(item.score, item.relevance_score, item.similarity));
    const paperId = firstPresent(item.paper_id, item.document_id, item.doc_id);
    return `
    <article class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(getItemTitle(item))}</strong>
          ${hasValue(paperId) ? `<p class="block-note">paper_id: ${escapeHtml(formatFieldValue(paperId))}</p>` : ""}
        </div>
        ${score ? `<div class="score-badge">\u5206\u6570 ${escapeHtml(score)}</div>` : ""}
      </header>
      ${renderEvidenceMeta(item, { includePaperId: false })}
      <div>
        <h4>\u5173\u952E\u7247\u6BB5</h4>
        ${renderHighlightList(item)}
      </div>
    </article>
  `;
  }).join("");

  detailOutput.innerHTML = cards;
}

export function renderCompareSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>\u5BF9\u6BD4\u7ED3\u8BBA</h3>
      <p class="summary-main">${escapeHtml(data.narrative || "")}</p>
    </div>
    <div class="summary-block">
      <h3>\u9605\u8BFB\u5EFA\u8BAE</h3>
      <p class="summary-subtext">\u5148\u770B\u603B\u8FF0\uFF0C\u518D\u770B\u6BCF\u7BC7\u8BBA\u6587\u7684\u201C\u65B9\u6CD5 / \u7ED3\u8BBA / \u5C40\u9650\u201D\u3002</p>
    </div>
  `;

  const cards = (data.rows || []).map((row) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(row.title)}</strong>
          <p class="block-note">${escapeHtml(row.paper_id)} \u00B7 ${escapeHtml(row.year)}</p>
        </div>
      </header>
      ${renderList("\u65B9\u6CD5", row.methods)}
      ${renderList("\u7ED3\u8BBA", row.findings)}
      ${renderList("\u5C40\u9650\u6027", row.limitations)}
    </div>
  `).join("");

  detailOutput.innerHTML = `${cards}${renderTrace(data.trace)}`;
}

export function renderReviewSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>\u7EFC\u8FF0\u7ED3\u8BBA</h3>
      <p class="summary-main">${escapeHtml(data.overview || "")}</p>
    </div>
    <div class="summary-block">
      <h3>\u9002\u5408\u600E\u4E48\u7528</h3>
      <p class="summary-subtext">\u5148\u770B\u8D8B\u52BF\u548C\u4EE3\u8868\u8BBA\u6587\uFF0C\u518D\u53C2\u8003\u9605\u8BFB\u987A\u5E8F\u548C\u5F00\u653E\u95EE\u9898\u3002</p>
    </div>
  `;

  detailOutput.innerHTML = `
    <div class="review-grid">
      ${renderList("\u8D8B\u52BF", data.trends)}
      ${renderList("\u4EE3\u8868\u8BBA\u6587", data.representative_papers)}
      ${renderList("\u9605\u8BFB\u987A\u5E8F", data.reading_order)}
      ${renderList("\u5F00\u653E\u95EE\u9898", data.open_problems)}
    </div>
    ${renderTrace(data.trace)}
  `;
}

export function renderEvaluateSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>\u8BC4\u6D4B\u6307\u6807</h3>
      <p class="summary-main">paper \u547D\u4E2D\u7387 ${escapeHtml(data.paper_hit_rate)} \u00B7 \u5173\u952E\u8BCD\u547D\u4E2D\u7387 ${escapeHtml(data.keyword_hit_rate)}</p>
      <p class="summary-meta">\u901A\u8FC7 ${escapeHtml(data.passed_cases)} / ${escapeHtml(data.num_cases)} \u00B7 \u5931\u8D25 ${escapeHtml(data.failed_cases)} \u00B7 \u5E73\u5747\u56DE\u7B54\u957F\u5EA6 ${escapeHtml(data.avg_answer_length)}</p>
    </div>
    <div class="summary-block">
      <h3>\u600E\u4E48\u770B\u7ED3\u679C</h3>
      <p class="summary-subtext">\u4F18\u5148\u770B\u5931\u8D25\u6837\u4F8B\uFF0C\u5B83\u4EEC\u6700\u9002\u5408\u62FF\u6765\u505A bad case \u5206\u6790\u548C\u540E\u7EED\u4F18\u5316\u3002</p>
    </div>
  `;

  const failures = (data.failures || []).map((item) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(item.case_id)}</strong>
          <p class="block-note">\u95EE\u9898\uFF1A${escapeHtml(item.question)}</p>
        </div>
      </header>
      <p class="block-note">\u547D\u4E2D\u60C5\u51B5\uFF1Apaper=${escapeHtml(item.paper_hit)} \u00B7 keyword=${escapeHtml(item.keyword_hit)}</p>
      <p class="block-note">\u671F\u671B\u8BBA\u6587\uFF1A${escapeHtml((item.expected_paper_ids || []).join(", "))}</p>
      <p class="block-note">\u5B9E\u9645\u5F15\u7528\uFF1A${escapeHtml((item.cited_ids || []).join(", "))}</p>
      <p>${escapeHtml(item.answer || "")}</p>
    </div>
  `).join("");

  const failurePanel = failures || `<div class="detail-block"><h4>\u5931\u8D25\u6837\u4F8B</h4><p class="block-note">\u5F53\u524D\u8BC4\u6D4B\u96C6\u5168\u90E8\u901A\u8FC7\uFF0C\u6CA1\u6709\u5931\u8D25\u6837\u4F8B\u3002</p></div>`;
  detailOutput.innerHTML = `${renderRagasPanel(data.ragas)}${failurePanel}`;
}

export function renderResult(mode, data) {
  if (mode === "search") {
    renderSearchSummary(data);
    return;
  }
  if (mode === "ask") {
    renderAskSummary(data);
    return;
  }
  if (mode === "rag_lab") {
    renderRagLabSummary(data);
    return;
  }
  if (mode === "compare") {
    renderCompareSummary(data);
    return;
  }
  if (mode === "review") {
    renderReviewSummary(data);
    return;
  }
  renderEvaluateSummary(data);
}
