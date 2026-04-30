import { summaryOutput, detailOutput } from "../state.js";
import { escapeHtml, renderSimpleMarkdown } from "./escape.js";
import { renderHistory } from "./common.js";
import { renderClaimAudit, renderEvidence, renderTrace, renderDiagnosticsPanel, renderContradictions } from "./evidence.js";
import { exportAnswer } from "../api.js";

export function renderAskSummary(data) {
  const helperTitle = data.insufficient_evidence ? "\u8BC1\u636E\u72B6\u6001" : "\u5FEB\u901F\u5224\u65AD";
  const helperText = data.insufficient_evidence
    ? "\u5F53\u524D\u95EE\u9898\u6CA1\u6709\u68C0\u7D22\u5230\u8DB3\u591F\u8BC1\u636E\uFF0C\u7CFB\u7EDF\u5DF2\u963B\u6B62\u81EA\u7531\u751F\u6210\u56DE\u7B54\u3002\u4F60\u53EF\u4EE5\u6362\u5173\u952E\u8BCD\u3001\u7F29\u5C0F\u95EE\u9898\u8303\u56F4\uFF0C\u6216\u5173\u95ED\u4E25\u683C\u8BC1\u636E\u6A21\u5F0F\u3002"
    : "\u5982\u679C\u56DE\u7B54\u91CC\u63D0\u5230\u4E86\u5177\u4F53\u8BBA\u6587\u548C\u673A\u5236\uFF0C\u518D\u5230\u4E0B\u65B9\u67E5\u770B\u8BC1\u636E\u4E0E\u8F68\u8FF9\u3002";
  const evidence = Array.isArray(data.evidence) ? data.evidence : [];
  const evidenceCount = evidence.length;
  const citedByMap = {};
  if (Array.isArray(data.claim_audit)) {
    for (const audit of data.claim_audit) {
      const refs = Array.isArray(audit.evidence_numbers) ? audit.evidence_numbers : [];
      for (const num of refs) {
        citedByMap[String(num)] = (citedByMap[String(num)] || 0) + 1;
      }
    }
  }
  const hasClaimAudit = Object.prototype.hasOwnProperty.call(data, "claim_audit");
  summaryOutput.innerHTML = `
    <div class="summary-block primary ${data.insufficient_evidence ? "warning" : ""}">
      <h3>\u56DE\u7B54</h3>
      <p class="summary-main cited-text">${renderSimpleMarkdown(data.answer || "", evidenceCount, evidence)}</p>
      <p class="summary-meta">\u4F1A\u8BDD\u6807\u9898\uFF1A${escapeHtml(data.session_title || "\u672A\u547D\u540D\u4F1A\u8BDD")}</p>
      ${data.retrieval_confidence > 0 ? (() => {
        const pct = (data.retrieval_confidence * 100).toFixed(0);
        const level = data.retrieval_confidence >= 0.6 ? "high" : data.retrieval_confidence >= 0.2 ? "mid" : "low";
        const label = level === "high" ? "\u9AD8" : level === "mid" ? "\u4E2D" : "\u4F4E";
        return `<div class="confidence-bar-wrap">
          <span class="confidence-label">\u68C0\u7D22\u7F6E\u4FE1\u5EA6</span>
          <div class="confidence-bar">
            <div class="confidence-bar-fill confidence-bar-${level}" style="width:${pct}%"></div>
          </div>
          <span class="confidence-pct confidence-${level}">${pct}%</span>
          <span class="confidence-level confidence-${level}">${label}</span>
        </div>`;
      })() : ""}
    </div>
    <div class="summary-block">
      <h3>${escapeHtml(helperTitle)}</h3>
      <p class="summary-subtext">${escapeHtml(helperText)}</p>
    </div>
    <div class="summary-block">
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="ghost-button compact-button" type="button" data-export-format="markdown">导出 Markdown</button>
        <button class="ghost-button compact-button" type="button" data-export-format="json">导出 JSON</button>
      </div>
    </div>
  `;
  const subQuestionsHtml = Array.isArray(data.sub_questions) && data.sub_questions.length > 0
    ? `<div class="detail-block"><details><summary style="cursor:pointer;user-select:none"><h4 style="display:inline">\u67E5\u8BE2\u5206\u89E3 (${data.sub_questions.length} \u4E2A\u5B50\u95EE\u9898)</h4></summary><div class="decompose-steps">${data.sub_questions.map((sq, i) => {
        const sqEvidence = Array.isArray(sq.evidence) ? sq.evidence.length : 0;
        const answerPreview = escapeHtml((sq.answer || "").slice(0, 300));
        const hasMore = (sq.answer || "").length > 300;
        return `<div class="decompose-step">
          <div class="decompose-step-num">${i + 1}</div>
          <div class="decompose-step-body">
            <p class="decompose-question"><strong>${escapeHtml(sq.question || "")}</strong></p>
            ${sqEvidence > 0 ? `<span class="decompose-evidence-badge">${sqEvidence} \u6761\u8BC1\u636E</span>` : ""}
            <div class="decompose-answer${hasMore ? " decompose-answer-truncated" : ""}">
              <p>${answerPreview}${hasMore ? "..." : ""}</p>
            </div>
          </div>
        </div>`;
      }).join("")}</div></details></div>`
    : "";
  detailOutput.innerHTML = `${renderHistory(data.history)}${subQuestionsHtml}${renderDiagnosticsPanel(data.diagnostics)}${renderClaimAudit(data.claim_audit, evidenceCount, { showEmpty: hasClaimAudit })}${renderEvidence(data.evidence, citedByMap)}${renderContradictions(data.contradictions)}${renderTrace(data.trace)}`;
  summaryOutput.querySelectorAll("[data-export-format]").forEach((btn) => {
    btn.addEventListener("click", () => {
      exportAnswer(data, btn.dataset.exportFormat);
    });
  });
}
