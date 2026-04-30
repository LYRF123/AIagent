import { summaryOutput, detailOutput } from "../state.js";
import { escapeHtml } from "./escape.js";
import { renderHistory } from "./common.js";
import { renderTextWithCitationChips, renderClaimAudit, renderEvidence, renderTrace } from "./evidence.js";

export function renderAskSummary(data) {
  const helperTitle = data.insufficient_evidence ? "\u8BC1\u636E\u72B6\u6001" : "\u5FEB\u901F\u5224\u65AD";
  const helperText = data.insufficient_evidence
    ? "\u5F53\u524D\u95EE\u9898\u6CA1\u6709\u68C0\u7D22\u5230\u8DB3\u591F\u8BC1\u636E\uFF0C\u7CFB\u7EDF\u5DF2\u963B\u6B62\u81EA\u7531\u751F\u6210\u56DE\u7B54\u3002\u4F60\u53EF\u4EE5\u6362\u5173\u952E\u8BCD\u3001\u7F29\u5C0F\u95EE\u9898\u8303\u56F4\uFF0C\u6216\u5173\u95ED\u4E25\u683C\u8BC1\u636E\u6A21\u5F0F\u3002"
    : "\u5982\u679C\u56DE\u7B54\u91CC\u63D0\u5230\u4E86\u5177\u4F53\u8BBA\u6587\u548C\u673A\u5236\uFF0C\u518D\u5230\u4E0B\u65B9\u67E5\u770B\u8BC1\u636E\u4E0E\u8F68\u8FF9\u3002";
  const evidenceCount = Array.isArray(data.evidence) ? data.evidence.length : 0;
  const hasClaimAudit = Object.prototype.hasOwnProperty.call(data, "claim_audit");
  summaryOutput.innerHTML = `
    <div class="summary-block primary ${data.insufficient_evidence ? "warning" : ""}">
      <h3>\u56DE\u7B54</h3>
      <p class="summary-main cited-text">${renderTextWithCitationChips(data.answer || "", evidenceCount)}</p>
      <p class="summary-meta">\u4F1A\u8BDD\u6807\u9898\uFF1A${escapeHtml(data.session_title || "\u672A\u547D\u540D\u4F1A\u8BDD")}</p>
    </div>
    <div class="summary-block">
      <h3>${escapeHtml(helperTitle)}</h3>
      <p class="summary-subtext">${escapeHtml(helperText)}</p>
    </div>
  `;
  detailOutput.innerHTML = `${renderHistory(data.history)}${renderClaimAudit(data.claim_audit, evidenceCount, { showEmpty: hasClaimAudit })}${renderEvidence(data.evidence)}${renderTrace(data.trace)}`;
}
