export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function hasValue(value) {
  return value !== undefined && value !== null && String(value).trim() !== "";
}

export function firstPresent(...values) {
  return values.find((value) => hasValue(value)) ?? "";
}

export function formatFieldValue(value) {
  if (!hasValue(value)) {
    return "";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function formatScoreValue(value) {
  if (!hasValue(value)) {
    return "";
  }
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return formatFieldValue(value);
  }
  return numericValue.toFixed(3).replace(/\.?0+$/, "");
}

export function formatPageValue(value) {
  const text = formatFieldValue(value);
  if (!text) {
    return "";
  }
  return /^\d+$/.test(text) ? `\u7B2C ${text} \u9875` : text;
}

export function getSafeHref(value) {
  const text = formatFieldValue(value).trim();
  if (!text) {
    return "";
  }
  if (text.startsWith("/")) {
    return text;
  }
  try {
    const url = new URL(text);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return text;
    }
  } catch {
    return "";
  }
  return "";
}

export function renderLinkedValue(value, label = value) {
  const text = formatFieldValue(label || value);
  const href = getSafeHref(value);
  if (!href) {
    return escapeHtml(text);
  }
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`;
}

export function renderMetaPill(label, contentHtml) {
  if (!contentHtml) {
    return "";
  }
  return `
    <span class="evidence-meta-pill">
      <span class="meta-label">${escapeHtml(label)}</span>
      ${contentHtml}
    </span>
  `;
}

export function renderEvidenceMeta(item, options = {}) {
  const pills = [];
  const paperId = firstPresent(item.paper_id, item.document_id, item.doc_id);
  const sourceUrl = firstPresent(item.source_url, item.url);
  const sourceLabel = firstPresent(item.source_label, item.source_title);
  const sourceFile = firstPresent(item.file_name, item.source_file, item.file_path, item.path, item.source);
  const page = firstPresent(item.page, item.page_number, item.page_label);
  const pageStart = firstPresent(item.page_start, item.start_page);
  const pageEnd = firstPresent(item.page_end, item.end_page);
  const locator = firstPresent(item.locator, item.location, item.anchor, item.chunk_id);

  if (options.includePaperId !== false && hasValue(paperId)) {
    pills.push(renderMetaPill("ID", escapeHtml(formatFieldValue(paperId))));
  }
  if (hasValue(sourceUrl)) {
    pills.push(renderMetaPill(hasValue(sourceLabel) ? "\u6765\u6E90" : "URL", renderLinkedValue(sourceUrl, hasValue(sourceLabel) ? sourceLabel : sourceUrl)));
  } else if (hasValue(sourceLabel)) {
    pills.push(renderMetaPill("\u6765\u6E90", escapeHtml(formatFieldValue(sourceLabel))));
  }
  if (hasValue(sourceFile) && sourceFile !== sourceLabel && sourceFile !== sourceUrl) {
    pills.push(renderMetaPill("\u6587\u4EF6", renderLinkedValue(sourceFile)));
  }
  if (hasValue(page)) {
    pills.push(renderMetaPill("\u9875\u7801", escapeHtml(formatPageValue(page))));
  } else if (hasValue(pageStart) || hasValue(pageEnd)) {
    const pageRange = hasValue(pageStart) && hasValue(pageEnd)
      ? `${formatFieldValue(pageStart)}-${formatFieldValue(pageEnd)}`
      : formatFieldValue(hasValue(pageStart) ? pageStart : pageEnd);
    pills.push(renderMetaPill("\u9875\u7801", escapeHtml(formatPageValue(pageRange))));
  }
  if (hasValue(locator)) {
    pills.push(renderMetaPill("\u5B9A\u4F4D", escapeHtml(formatFieldValue(locator))));
  }

  if (pills.length === 0) {
    return "";
  }
  const classes = ["evidence-meta", options.className].filter(Boolean).join(" ");
  return `<div class="${classes}">${pills.join("")}</div>`;
}

export function getItemTitle(item) {
  return firstPresent(item.title, item.source_label, item.file_name, item.paper_id, "\u672A\u547D\u540D\u6587\u6863");
}

export function getItemText(item) {
  return firstPresent(item.text, item.snippet, item.highlight, item.highlight_text, item.excerpt, item.content, item.quote, "\u672A\u8FD4\u56DE\u7247\u6BB5\u6587\u672C\u3002");
}

export function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }
  return timestamp.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function firstArrayValue(...values) {
  return values.find((value) => Array.isArray(value)) || [];
}

export function firstObjectValue(...values) {
  return values.find((value) => isPlainObject(value)) || {};
}

export function firstDefinedValue(...values) {
  return values.find((value) => value !== undefined && value !== null);
}

export function firstScalarValue(...values) {
  return values.find((value) => (
    hasValue(value) && !isPlainObject(value) && !Array.isArray(value)
  )) ?? "";
}

export function truncateText(value, maxLength = 120) {
  const text = formatFieldValue(value).trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 3))}...`;
}

export function formatSignedScore(value) {
  if (!hasValue(value)) {
    return "";
  }
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return formatFieldValue(value);
  }
  const formatted = formatScoreValue(numericValue);
  return numericValue > 0 ? `+${formatted}` : formatted;
}

export function normalizeStageKey(value) {
  return formatFieldValue(value).trim().toLowerCase().replace(/[\s-]+/g, "_");
}

export function renderSimpleMarkdown(text, evidenceCount = 0, evidence = []) {
  if (!hasValue(text)) {
    return "";
  }
  let html = escapeHtml(String(text));

  // Bold: **text**
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Inline code: `code`
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

  // Paragraphs: split on double newline
  const blocks = html.split(/\n{2,}/);
  html = blocks
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      // List block: consecutive lines starting with "- "
      const lines = trimmed.split("\n");
      const isListBlock = lines.every((l) => l.trimStart().startsWith("- ") || l.trim() === "");
      if (isListBlock) {
        const items = lines
          .filter((l) => l.trimStart().startsWith("- "))
          .map((l) => `<li>${l.trimStart().slice(2)}</li>`)
          .join("");
        return `<ul class="md-list">${items}</ul>`;
      }
      // Regular paragraph
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    })
    .filter(Boolean)
    .join("");

  // Citation chips: [N] → clickable buttons (same as renderTextWithCitationChips)
  html = html.replace(/\[(\d+)\]/g, (match, number) => {
    const num = Number(number);
    const isMatched = num >= 1 && num <= evidenceCount;
    const classes = `citation-chip${isMatched ? "" : " citation-chip-unmatched"}`;
    const evidenceItem = num >= 1 && num <= evidence.length ? evidence[num - 1] : null;
    const titleAttr = evidenceItem
      ? ` title="${escapeHtml(truncateText(evidenceItem.text || "", 160))}"`
      : "";
    return `<button class="${classes}" type="button" data-citation-target="${escapeHtml(String(number))}"${titleAttr} aria-label="Citation ${escapeHtml(String(number))}">[${escapeHtml(String(number))}]</button>`;
  });

  return html;
}
