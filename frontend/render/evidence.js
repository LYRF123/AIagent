import { detailOutput, getActiveEvidenceHighlightTimeout, setActiveEvidenceHighlightTimeout, sectionLabels, claimStatusLabels } from "../state.js";
import {
  escapeHtml,
  hasValue,
  firstPresent,
  formatFieldValue,
  formatScoreValue,
  formatPageValue,
  renderEvidenceMeta,
  getItemTitle,
  getItemText,
  isPlainObject,
  firstArrayValue,
  firstDefinedValue,
  firstScalarValue,
  truncateText,
} from "./escape.js";
import { setStatus } from "./common.js";

export function renderTextWithCitationChips(value, evidenceCount = 0, evidence = []) {
  const text = formatFieldValue(value);
  let html = "";
  let lastIndex = 0;
  text.replace(/\[(\d+)\]/g, (match, number, offset) => {
    html += escapeHtml(text.slice(lastIndex, offset));
    const isMatched = Number(number) >= 1 && Number(number) <= evidenceCount;
    const classes = `citation-chip${isMatched ? "" : " citation-chip-unmatched"}`;
    const evidenceItem = Number(number) >= 1 && Number(number) <= evidence.length ? evidence[Number(number) - 1] : null;
    const titleAttr = evidenceItem ? ` title="${escapeHtml(truncateText(evidenceItem.text || '', 160))}"` : "";
    html += `<button class="${classes}" type="button" data-citation-target="${escapeHtml(number)}"${titleAttr} aria-label="Citation ${escapeHtml(number)}">[${escapeHtml(number)}]</button>`;
    lastIndex = offset + match.length;
    return match;
  });
  html += escapeHtml(text.slice(lastIndex));
  return html;
}

export function focusEvidenceCard(number, options = {}) {
  const targetNumber = formatFieldValue(number).replace(/[^\d]/g, "");
  if (!targetNumber) {
    return;
  }
  const card = detailOutput.querySelector(`[data-evidence-number="${targetNumber}"]`);
  if (!card) {
    setStatus(`\u672A\u627E\u5230\u8BC1\u636E ${targetNumber}`, "error");
    return;
  }

  detailOutput.querySelectorAll(".evidence-item.is-highlighted").forEach((item) => {
    item.classList.remove("is-highlighted");
  });
  window.clearTimeout(getActiveEvidenceHighlightTimeout());
  card.classList.add("is-highlighted");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  if (options.moveFocus !== false) {
    card.focus({ preventScroll: true });
  }
  setActiveEvidenceHighlightTimeout(window.setTimeout(() => {
    card.classList.remove("is-highlighted");
  }, 3200));
}

export function renderHighlightList(item) {
  const highlights = Array.isArray(item.highlights) ? item.highlights : (hasValue(item.highlights) ? [item.highlights] : []);
  if (highlights.length === 0) {
    return `<p class="block-note">\u6CA1\u6709\u8FD4\u56DE highlights\u3002</p>`;
  }
  return `
    <ul class="highlight-list">
      ${highlights.map((highlight) => {
        const highlightItem = highlight && typeof highlight === "object" && !Array.isArray(highlight)
          ? highlight
          : { text: highlight };
        const mergedItem = { ...item, ...highlightItem };
        return `
          <li>
            <span>${escapeHtml(getItemText(highlightItem))}</span>
            ${renderEvidenceMeta(mergedItem, { includePaperId: false, className: "highlight-meta" })}
          </li>
        `;
      }).join("")}
    </ul>
  `;
}

export function renderTrace(trace) {
  if (!trace || trace.length === 0) {
    return `<div class="detail-block"><h4>\u8C03\u7528\u8F68\u8FF9</h4><p class="block-note">\u6CA1\u6709\u8F68\u8FF9\u4FE1\u606F\u3002</p></div>`;
  }
  const rows = trace.map((item) => `
    <div class="trace-item">
      <header>
        <strong>${escapeHtml(item.tool)}</strong>
      </header>
      <p class="block-note">\u8F93\u5165\uFF1A${escapeHtml(item.input || "")}</p>
      <p>${escapeHtml(item.output || "")}</p>
    </div>
  `).join("");
  return `<div class="detail-block"><h4>\u8C03\u7528\u8F68\u8FF9</h4>${rows}</div>`;
}

export function renderEvidence(evidence, citedByMap = {}) {
  if (!evidence || evidence.length === 0) {
    return `<div class="detail-block"><h4>\u8BC1\u636E\u7247\u6BB5</h4><p class="block-note">\u5F53\u524D\u7ED3\u679C\u6CA1\u6709\u8FD4\u56DE\u8BC1\u636E\u3002</p></div>`;
  }
  const rows = evidence.map((item, index) => {
    const evidenceNumber = String(index + 1);
    const paperId = firstPresent(item.paper_id, item.document_id, item.doc_id);
    const section = firstPresent(item.section, item.section_label);
    const sectionLabel = formatFieldValue(section);
    const score = formatScoreValue(firstPresent(item.score, item.relevance_score, item.similarity));
    const citedByCount = citedByMap[evidenceNumber] || 0;
    return `
    <article class="evidence-item" id="evidence-${escapeHtml(evidenceNumber)}" data-evidence-number="${escapeHtml(evidenceNumber)}" tabindex="-1">
      <header>
        <div class="evidence-title-row">
          <span class="evidence-number">[${escapeHtml(evidenceNumber)}]</span>
          <div>
            <strong>${escapeHtml(getItemTitle(item))}</strong>
            ${hasValue(paperId) ? `<p class="block-note">paper_id: ${escapeHtml(formatFieldValue(paperId))}</p>` : ""}
          </div>
        </div>
        ${score ? `<div class="score-badge">\u5206\u6570 ${escapeHtml(score)}</div>` : ""}
        ${citedByCount > 0 ? `<div class="cited-by-badge" data-cited-by="${citedByCount}">\u88AB ${citedByCount} \u6761 claim \u5F15\u7528</div>` : ""}
      </header>
      ${hasValue(section) ? `<div class="evidence-section">${escapeHtml(sectionLabels[sectionLabel] || sectionLabel)}</div>` : ""}
      ${renderEvidenceMeta(item, { includePaperId: false })}
      ${(() => {
        const fullText = getItemText(item);
        if (fullText.length <= 200) {
          return `<p class="evidence-text">${escapeHtml(fullText)}</p>`;
        }
        return `<div class="evidence-text-wrap">
          <p class="evidence-text evidence-text-collapsed">${escapeHtml(fullText)}</p>
          <button class="evidence-expand-btn ghost-button compact-button" type="button" data-expanded="false">展开全文</button>
        </div>`;
      })()}
    </article>
  `;
  }).join("");
  return `<div class="detail-block evidence-list-block"><h4>\u8BC1\u636E\u7247\u6BB5</h4><div class="evidence-list">${rows}</div></div>`;
}

export function normalizeClaimStatus(value) {
  const status = formatFieldValue(value).trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (["support", "supported", "verified", "yes"].includes(status)) {
    return "supported";
  }
  if (["weak", "partial", "partially_supported", "insufficient", "unclear"].includes(status)) {
    return "weak";
  }
  if (["unsupported", "not_supported", "false", "no"].includes(status)) {
    return "unsupported";
  }
  if (["citation_mismatch", "mismatch", "wrong_citation", "citation_error"].includes(status)) {
    return "citation_mismatch";
  }
  return status || "weak";
}

export function getClaimAuditItems(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (!isPlainObject(value)) {
    return hasValue(value) ? [{ claim: value }] : [];
  }

  const directItems = firstArrayValue(value.claims, value.items, value.entries, value.audits, value.results, value.claim_audit);
  if (directItems.length > 0) {
    return directItems;
  }

  const singleRowKeys = [
    "claim",
    "text",
    "statement",
    "sentence",
    "status",
    "verdict",
    "reason",
    "evidence_numbers",
    "supporting_quotes",
  ];
  if (singleRowKeys.some((key) => Object.prototype.hasOwnProperty.call(value, key))) {
    return [value];
  }

  return Object.entries(value).map(([claim, item]) => (
    isPlainObject(item) ? { claim, ...item } : { claim, status: item }
  ));
}

export function collectEvidenceRefs(value) {
  const refs = [];
  const addRefs = (item) => {
    if (item === undefined || item === null) {
      return;
    }
    if (Array.isArray(item)) {
      item.forEach(addRefs);
      return;
    }
    if (isPlainObject(item)) {
      addRefs(firstDefinedValue(
        item.evidence_number,
        item.evidence_num,
        item.number,
        item.ref,
        item.reference,
        item.citation,
        item.index,
      ));
      return;
    }
    const matches = formatFieldValue(item).match(/\d+/g) || [];
    matches.forEach((match) => refs.push(match));
  };

  addRefs(value);
  return Array.from(new Set(refs.filter((ref) => Number(ref) > 0)));
}

export function normalizeSupportingQuotes(value) {
  if (value === undefined || value === null) {
    return [];
  }
  const items = Array.isArray(value) ? value : [value];
  return items
    .map((item) => {
      if (isPlainObject(item)) {
        return firstScalarValue(item.quote, item.text, item.snippet, item.excerpt, item.content);
      }
      return formatFieldValue(item);
    })
    .filter(hasValue);
}

export function normalizeClaimAuditRow(item, index) {
  const row = isPlainObject(item) ? item : { claim: item };
  const status = normalizeClaimStatus(firstDefinedValue(row.status, row.verdict, row.label, row.support_status, row.classification));
  const evidenceRefs = collectEvidenceRefs(firstDefinedValue(
    row.evidence_numbers,
    row.evidence_refs,
    row.evidence_ref,
    row.citation_numbers,
    row.citations,
    row.refs,
    row.references,
    row.evidence,
  ));
  return {
    claim: firstPresent(row.claim, row.text, row.statement, row.sentence, row.content, `Claim ${index + 1}`),
    status,
    evidenceRefs,
    reason: firstScalarValue(row.reason, row.rationale, row.explanation, row.note),
    quotes: normalizeSupportingQuotes(firstDefinedValue(
      row.supporting_quotes,
      row.supporting_quote,
      row.quotes,
      row.quote,
      row.evidence_quotes,
    )),
  };
}

export function renderClaimEvidenceRefs(refs, evidenceCount) {
  if (!refs || refs.length === 0) {
    return `<span class="claim-ref-empty">no refs</span>`;
  }
  return `
    <div class="claim-evidence-refs" aria-label="Evidence references">
      ${refs.map((number) => {
        const isMatched = Number(number) >= 1 && Number(number) <= evidenceCount;
        const classes = `citation-chip${isMatched ? "" : " citation-chip-unmatched"}`;
        return `<button class="${classes}" type="button" data-citation-target="${escapeHtml(number)}" aria-label="Citation ${escapeHtml(number)}">[${escapeHtml(number)}]</button>`;
      }).join("")}
    </div>
  `;
}

export function renderClaimAudit(claimAudit, evidenceCount = 0, options = {}) {
  const items = getClaimAuditItems(claimAudit).map(normalizeClaimAuditRow);
  if (items.length === 0) {
    if (!options.showEmpty) {
      return "";
    }
    return `
      <div class="detail-block claim-audit-block">
        <h4>Claim Audit</h4>
        <p class="block-note">\u5F53\u524D\u7ED3\u679C\u6CA1\u6709\u8FD4\u56DE\u53EF\u5BA1\u8BA1\u7684 claim\u3002</p>
      </div>
    `;
  }

  return `
    <div class="detail-block claim-audit-block">
      <div class="claim-audit-head">
        <h4>Claim Audit</h4>
        <span>${escapeHtml(items.length)} claims</span>
      </div>
      <div class="claim-audit-list">
        ${items.map((item) => {
          const statusClass = claimStatusLabels[item.status] ? item.status : "weak";
          return `
            <article class="claim-audit-row">
              <div class="claim-audit-row-head">
                <span class="claim-status claim-status-${escapeHtml(statusClass)}">${escapeHtml(claimStatusLabels[item.status] || item.status)}</span>
                ${renderClaimEvidenceRefs(item.evidenceRefs, evidenceCount)}
              </div>
              <p class="claim-text">${escapeHtml(formatFieldValue(item.claim))}</p>
              ${hasValue(item.reason) ? `<p class="claim-reason"><span>Reason</span>${escapeHtml(truncateText(item.reason, 180))}</p>` : ""}
              ${item.quotes.length > 0 ? `
                <div class="claim-quotes">
                  ${item.quotes.slice(0, 2).map((quote) => `<p>${escapeHtml(truncateText(quote, 180))}</p>`).join("")}
                </div>
              ` : ""}
            </article>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

export function renderDiagnosticsPanel(diagnostics) {
  if (!diagnostics || !diagnostics.pipeline_stages || diagnostics.pipeline_stages.length === 0) {
    return "";
  }
  const stages = diagnostics.pipeline_stages;
  const totalMs = diagnostics.latency_ms != null ? Number(diagnostics.latency_ms) : 0;
  const maxLatency = Math.max(...stages.map((s) => Number(s.latency_ms) || 0), 1);

  const stageRows = stages.map((stage, idx) => {
    const name = escapeHtml(formatFieldValue(stage.name || `stage_${idx}`));
    const status = stage.status || "unknown";
    const statusClass = status === "completed" ? "success" : status === "failed" ? "error" : status === "skipped" ? "idle" : "loading";
    const latencyMs = Number(stage.latency_ms) || 0;
    const widthPct = Math.max((latencyMs / maxLatency) * 100, 4);
    const latencyLabel = stage.latency_ms != null ? `${latencyMs.toFixed(0)}ms` : "";
    const hitCount = Array.isArray(stage.top) ? stage.top.length : 0;
    return `
      <div class="pipeline-row">
        <div class="pipeline-row-label">
          <span class="pipeline-step-num">${idx + 1}</span>
          <strong>${name}</strong>
          <span class="status-pill ${statusClass}" style="min-height:auto;padding:2px 6px;font-size:11px">${escapeHtml(status)}</span>
        </div>
        <div class="pipeline-bar-track">
          <div class="pipeline-bar pipeline-bar-${statusClass}" style="width:${widthPct.toFixed(1)}%">
            ${latencyLabel ? `<span class="pipeline-bar-label">${escapeHtml(latencyLabel)}</span>` : ""}
          </div>
        </div>
        ${hitCount > 0 ? `<span class="pipeline-hits">${hitCount} hits</span>` : ""}
      </div>
    `;
  }).join("");

  return `
    <div class="detail-block">
      <details>
        <summary style="cursor:pointer;user-select:none">
          <h4 style="display:inline">\u68C0\u7D22\u7BA1\u7EBF${totalMs ? ` (${totalMs.toFixed(0)}ms)` : ""}</h4>
        </summary>
        <div class="pipeline-waterfall" style="margin-top:8px">
          ${stageRows}
        </div>
      </details>
    </div>
  `;
}

export function renderContradictions(contradictions) {
  if (!Array.isArray(contradictions) || contradictions.length === 0) {
    return "";
  }
  const rows = contradictions.map((c) => {
    const severityClass = c.severity === "major" ? "danger" : c.severity === "minor" ? "neutral" : "warning";
    return `
      <div class="contradiction-warning">
        <div class="contradiction-head">
          <span class="failure-tag ${severityClass}">${escapeHtml(c.severity || "moderate")}</span>
          <span class="block-note">证据 <button class="citation-chip" type="button" data-citation-target="${escapeHtml(String(c.evidence_a))}" aria-label="Citation ${escapeHtml(String(c.evidence_a))}">[${escapeHtml(String(c.evidence_a))}]</button> vs <button class="citation-chip" type="button" data-citation-target="${escapeHtml(String(c.evidence_b))}" aria-label="Citation ${escapeHtml(String(c.evidence_b))}">[${escapeHtml(String(c.evidence_b))}]</button></span>
        </div>
        <p>${escapeHtml(c.description || "")}</p>
      </div>
    `;
  }).join("");
  return `
    <div class="detail-block">
      <h4>矛盾检测 (${contradictions.length})</h4>
      <div style="display:grid;gap:6px">${rows}</div>
    </div>
  `;
}

export function renderRagasPanel(ragas) {
  if (!ragas) {
    return "";
  }
  if (ragas.skipped) {
    return `
      <div class="detail-block">
        <h4>Ragas \u8BC4\u4F30</h4>
        <p class="block-note">${escapeHtml(ragas.reason || "Ragas \u6307\u6807\u672A\u8FD0\u884C\u3002")}</p>
      </div>
    `;
  }

  const summaryRows = Object.entries(ragas.summary || {}).map(([name, value]) => `
    <li>${escapeHtml(name)}\uFF1A${escapeHtml(value)}</li>
  `).join("");
  const perCaseRows = (ragas.per_case || []).map((item) => `
    <div class="trace-item">
      <header><strong>${escapeHtml(item.case_id)}</strong></header>
      <p>${Object.entries(item)
        .filter(([key]) => key !== "case_id")
        .map(([key, value]) => `${escapeHtml(key)}=${escapeHtml(value)}`)
        .join(" \u00B7 ")}</p>
    </div>
  `).join("");

  return `
    <div class="detail-block">
      <h4>Ragas \u8BC4\u4F30</h4>
      <ul>${summaryRows || "<li>\u6682\u65E0\u6C47\u603B\u5206\u6570</li>"}</ul>
      ${perCaseRows}
    </div>
  `;
}
