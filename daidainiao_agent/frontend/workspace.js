import {
  listKnowledgeDocuments,
  getDocumentDetail,
  getDocumentBrief,
  deleteDocument,
  runRagLab,
  runDeepReview,
  getRuntimeStatus,
} from "./api.js";
import { getLastFinalPayload } from "./final-payload.js";
import {
  escapeHtml,
  truncateText,
  renderEvidenceMeta,
  getItemTitle,
  getItemText,
  formatScoreValue,
} from "./render/escape.js";
import { confirmAction } from "./confirm.js";
import {
  dismissSettingsPanelAnimated,
  setWorkspaceShellInert,
  showWorkspaceScrim,
  focusWorkspaceToggle,
  bindWorkspaceFocusTrap,
  removeWorkspaceFocusTrap,
  focusWorkspaceCloseButton,
} from "./overlay.js";

let cachedDocuments = [];

function el(id) {
  return document.getElementById(id);
}

function setOutput(target, html) {
  const node = typeof target === "string" ? el(target) : target;
  if (node) node.innerHTML = html;
}

function setLoading(target, message = "读取中...") {
  setOutput(target, `<p class="settings-empty">${escapeHtml(message)}</p>`);
}

function setError(target, error) {
  setOutput(target, `<p class="workspace-error">错误：${escapeHtml(error.message || String(error) || "请求失败")}</p>`);
}

async function withButtonBusy(buttonId, task) {
  const button = el(buttonId);
  if (button?.disabled) return;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    await task();
  } finally {
    if (button) {
      button.disabled = false;
      button.setAttribute("aria-busy", "false");
    }
  }
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${Math.round(numeric * 100)}%`;
}

function formatStageLabel(name) {
  const labels = {
    tfidf: "TF-IDF",
    bm25: "BM25",
    vector: "向量",
    fusion: "融合",
    rerank: "重排",
    query_expansion: "扩展",
  };
  return labels[name] || name || "阶段";
}

function formatLatency(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}s`;
  return `${Math.round(numeric)}ms`;
}

export function openWorkspaceTab(tabName) {
  openWorkspace();
  activateTab(tabName);
}

export async function jumpToReadingSource({ paperId, page, highlightText = "" }) {
  if (!paperId) return;
  openWorkspaceTab("reading");
  await refreshWorkspaceDocuments();
  const select = el("workspace-reading-select");
  if (select) select.value = paperId;
  setLoading("workspace-reading-output", "加载来源片段…");
  try {
    const detail = await getDocumentDetail(paperId, { passageLimit: 24 });
    let passages = detail.passages || [];
    if (page) {
      const filtered = passages.filter((item) => String(item.page) === String(page));
      if (filtered.length) passages = filtered;
    }
    if (highlightText && passages.length > 1) {
      const needle = highlightText.slice(0, 48).toLowerCase();
      const matched = passages.filter((item) => (item.text || "").toLowerCase().includes(needle));
      if (matched.length) passages = matched;
    }
    const highlight = highlightText.slice(0, 200);
    setOutput("workspace-reading-output", `
      <div class="workspace-stack">
        <article class="workspace-card workspace-card-highlight">
          <div class="workspace-card-head">
            <strong>${escapeHtml(detail.title || paperId)}</strong>
            <span>${page ? `第 ${escapeHtml(String(page))} 页` : "来源片段"}</span>
          </div>
          <p class="block-note">从对话证据跳转至此。下方为语料中的相关段落。</p>
        </article>
        ${passages.length ? passages.map((item) => `
          <details class="workspace-detail evidence-passage-detail" ${highlight && (item.text || "").includes(highlight.slice(0, 40)) ? "open" : ""}>
            <summary>${escapeHtml(item.section || "片段")}${item.page != null ? ` · 第 ${escapeHtml(String(item.page))} 页` : ""}</summary>
            <p class="evidence-passage-text">${escapeHtml(item.text || "")}</p>
          </details>
        `).join("") : `<p class="settings-empty">未找到匹配段落，可尝试生成阅读简报。</p>`}
        <button type="button" class="ghost-button compact-button" id="workspace-reading-brief-from-source">生成完整简报</button>
      </div>
    `);
    el("workspace-reading-brief-from-source")?.addEventListener("click", () => renderReadingBrief(paperId), { once: true });
  } catch (error) {
    setError("workspace-reading-output", error);
  }
}

function bindLabOutputActions() {
  const output = el("workspace-lab-output");
  if (!output) return;
  output.querySelectorAll(".lab-replay-btn").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const question = button.dataset.question || "";
      const input = document.getElementById("chat-input");
      if (input && question) {
        input.value = question;
        input.focus();
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
  });
}

function renderMiniMetric(label, value) {
  return `
    <div class="workspace-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
    </div>
  `;
}

function renderEvidenceItem(item, index) {
  return `
    <article class="workspace-card evidence-workspace-card">
      <div class="workspace-card-head">
        <span class="workspace-rank">[${index + 1}]</span>
        <strong>${escapeHtml(truncateText(getItemTitle(item), 90))}</strong>
      </div>
      ${renderEvidenceMeta(item, { includePaperId: true })}
      <p>${escapeHtml(truncateText(getItemText(item), 360))}</p>
      <div class="workspace-card-foot">
        <span>${escapeHtml(item.section || "片段")}</span>
        <span>score ${escapeHtml(formatScoreValue(item.score) || "-")}</span>
      </div>
    </article>
  `;
}

export function renderLatestEvidence() {
  const data = getLastFinalPayload();
  if (!data) {
    setOutput("workspace-evidence-output", `<p class="settings-empty">还没有可展示的最新回答。先问一个问题，再回来看证据链。</p>`);
    return;
  }
  const evidence = Array.isArray(data.evidence) ? data.evidence : [];
  const audits = Array.isArray(data.claim_audit) ? data.claim_audit : [];
  const stages = Array.isArray(data.diagnostics?.pipeline_stages) ? data.diagnostics.pipeline_stages : [];
  const html = `
    <div class="workspace-stack">
      <div class="workspace-answer-preview">
        <span>最新问题</span>
        <strong>${escapeHtml(truncateText(data.question || "", 140))}</strong>
        <p>${escapeHtml(truncateText(data.answer || "", 420))}</p>
      </div>
      <div class="workspace-metrics-row">
        ${renderMiniMetric("证据", evidence.length)}
        ${renderMiniMetric("Claim", audits.length)}
        ${renderMiniMetric("链路阶段", stages.length)}
      </div>
      ${audits.length ? `
        <div class="workspace-subsection">
          <h4>Claim Audit</h4>
          ${audits.map((item) => `
            <div class="audit-row audit-${escapeHtml(item.status || "unknown")}">
              <strong>${escapeHtml(item.status || "unknown")}</strong>
              <span>${escapeHtml(truncateText(item.claim || "", 190))}</span>
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${stages.length ? `
        <div class="workspace-subsection">
          <h4>检索链路 ${data.diagnostics?.latency_ms ? `· ${escapeHtml(formatLatency(data.diagnostics.latency_ms))}` : ""}</h4>
          <div class="workspace-stage-grid">
            ${stages.map((stage) => `
              <div class="workspace-stage">
                <span>${escapeHtml(formatStageLabel(stage.name))}</span>
                <strong>${escapeHtml(stage.status || "unknown")}</strong>
                ${formatLatency(stage.latency_ms) ? `<small>${escapeHtml(formatLatency(stage.latency_ms))}</small>` : ""}
              </div>
            `).join("")}
          </div>
        </div>
      ` : ""}
      <div class="workspace-subsection">
        <h4>证据片段</h4>
        ${evidence.length ? evidence.map(renderEvidenceItem).join("") : `<p class="settings-empty">这次回答没有返回证据。</p>`}
      </div>
    </div>
  `;
  setOutput("workspace-evidence-output", html);
}

function renderDocumentCard(item) {
  return `
    <article class="workspace-card document-card" data-paper-id="${escapeHtml(item.paper_id)}">
      <div class="workspace-card-head">
        <strong>${escapeHtml(truncateText(item.title || item.paper_id, 100))}</strong>
        <span class="doc-kind">${item.imported ? "导入" : "内置"}</span>
      </div>
      <p>${escapeHtml(truncateText(item.summary_preview || "", 260))}</p>
      <div class="workspace-card-foot">
        <span>${escapeHtml(String(item.year || ""))} ${escapeHtml(item.venue || "")}</span>
        <span>${escapeHtml(String(item.chunk_count || 0))} chunks</span>
      </div>
      <div class="workspace-actions-row">
        <button class="ghost-button compact-button document-detail-button" type="button" data-paper-id="${escapeHtml(item.paper_id)}">详情</button>
        <button class="ghost-button compact-button document-brief-button" type="button" data-paper-id="${escapeHtml(item.paper_id)}">阅读</button>
        ${item.imported ? `<button class="ghost-button compact-button document-delete-button" type="button" data-paper-id="${escapeHtml(item.paper_id)}">删除</button>` : ""}
      </div>
    </article>
  `;
}

function syncReadingSelect(items) {
  const select = el("workspace-reading-select");
  if (!select) return;
  select.innerHTML = items.map((item) => `
    <option value="${escapeHtml(item.paper_id)}">${escapeHtml(truncateText(item.title || item.paper_id, 90))}</option>
  `).join("");
}

export async function refreshWorkspaceDocuments() {
  setLoading("workspace-documents-output", "读取知识库...");
  try {
    const data = await listKnowledgeDocuments({ includeBase: true });
    cachedDocuments = data.items || [];
    syncReadingSelect(cachedDocuments);
    // 更新全部删除按钟可见性：有导入文档才显示
    const deleteAllBtn = el("workspace-delete-all-documents");
    if (deleteAllBtn) {
      const importedCount = cachedDocuments.filter((d) => d.imported).length;
      deleteAllBtn.style.display = importedCount > 0 ? "" : "none";
    }
    if (!cachedDocuments.length) {
      setOutput("workspace-documents-output", `<p class="settings-empty">知识库还没有文档。</p>`);
      return;
    }
    setOutput("workspace-documents-output", cachedDocuments.map(renderDocumentCard).join(""));
  } catch (error) {
    setError("workspace-documents-output", error);
  }
}

async function showDocumentDetail(paperId) {
  setLoading("workspace-documents-output", "读取文档详情...");
  try {
    const detail = await getDocumentDetail(paperId, { passageLimit: 8 });
    const passages = Array.isArray(detail.passages) ? detail.passages : [];
    setOutput("workspace-documents-output", `
      <div class="workspace-stack">
        <button id="workspace-documents-back" class="ghost-button compact-button" type="button">返回列表</button>
        <article class="workspace-card">
          <div class="workspace-card-head">
            <strong>${escapeHtml(detail.title || detail.paper_id)}</strong>
            <span class="doc-kind">${detail.imported ? "导入" : "内置"}</span>
          </div>
          <p>${escapeHtml(detail.summary || "")}</p>
          <div class="workspace-metrics-row">
            ${renderMiniMetric("Chunks", detail.chunk_count || 0)}
            ${renderMiniMetric("页数", detail.page_count || "-")}
            ${renderMiniMetric("年份", detail.year || "-")}
          </div>
        </article>
        <div class="workspace-subsection">
          <h4>片段预览</h4>
          ${passages.map((item) => `
            <details class="workspace-detail">
              <summary>${escapeHtml(item.section || "summary")} ${item.page ? `· 第 ${escapeHtml(String(item.page))} 页` : ""}</summary>
              <p>${escapeHtml(item.text || "")}</p>
            </details>
          `).join("")}
        </div>
      </div>
    `);
  } catch (error) {
    setError("workspace-documents-output", error);
  }
}

export async function renderReadingBrief(paperId) {
  await withButtonBusy("workspace-run-reading", async () => {
  const selected = paperId || el("workspace-reading-select")?.value;
  if (!selected) {
    setOutput("workspace-reading-output", `<p class="settings-empty">请先选择文档。</p>`);
    return;
  }
  setLoading("workspace-reading-output", "生成阅读简报...");
  try {
    const brief = await getDocumentBrief(selected);
    const sectionList = (title, items) => `
      <div class="workspace-subsection">
        <h4>${escapeHtml(title)}</h4>
        ${items && items.length ? `<ul class="workspace-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p class="settings-empty">暂无内容。</p>`}
      </div>
    `;
    setOutput("workspace-reading-output", `
      <div class="workspace-stack">
        <article class="workspace-card">
          <div class="workspace-card-head">
            <strong>${escapeHtml(brief.title || brief.paper_id)}</strong>
            <span>${escapeHtml(String(brief.year || ""))}</span>
          </div>
          <p>${escapeHtml(brief.summary || "")}</p>
        </article>
        ${sectionList("方法", brief.methods || [])}
        ${sectionList("发现", brief.findings || [])}
        ${sectionList("局限", brief.limitations || [])}
        ${sectionList("术语", brief.terms || [])}
        ${sectionList("必读问题", brief.suggested_questions || [])}
      </div>
    `);
  } catch (error) {
    setError("workspace-reading-output", error);
  }
  });
}

function renderLabResults(payload) {
  const summary = payload.summary || [];
  const failures = payload.failures || [];
  const perCase = payload.per_case || [];
  return `
    <div class="workspace-stack">
      <div class="workspace-metrics-row">
        ${renderMiniMetric("Cases", payload.num_cases || 0)}
        ${renderMiniMetric("失败项", failures.length)}
        ${renderMiniMetric("配置", summary.length)}
      </div>
      ${summary.map((row) => `
        <article class="workspace-card workspace-card-highlight">
          <div class="workspace-card-head">
            <strong>${escapeHtml(row.config_id)}</strong>
            <span>${row.use_rerank ? "rerank" : "fusion"}</span>
          </div>
          <div class="workspace-metrics-row">
            ${renderMiniMetric("hit@k", formatPercent(row.hit_at_k))}
            ${renderMiniMetric("MRR", row.mrr)}
            ${renderMiniMetric("关键词", formatPercent(row.keyword_coverage))}
          </div>
        </article>
      `).join("")}
      <div class="workspace-subsection">
        <h4>失败案例</h4>
        ${failures.length ? failures.slice(0, 8).map((item) => {
          const caseRow = perCase.find((row) => row.case_id === item.case_id);
          const question = caseRow?.question || item.question || "";
          return `
            <div class="failure-row">
              <strong>${escapeHtml(item.case_id)} · ${escapeHtml(item.config_id)}</strong>
              ${question ? `<p class="block-note">${escapeHtml(truncateText(question, 160))}</p>` : ""}
              <span>${escapeHtml((item.reasons || []).join(", "))}</span>
              ${question ? `<button type="button" class="ghost-button compact-button lab-replay-btn" data-question="${escapeHtml(question)}">在对话中复现</button>` : ""}
            </div>
          `;
        }).join("") : `<p class="settings-empty">当前配置没有失败项。</p>`}
      </div>
    </div>
  `;
}

export async function runWorkspaceLabBaseline() {
  await withButtonBusy("workspace-run-lab-baseline", async () => {
  const topK = Number(el("workspace-lab-top-k")?.value || 5);
  const candidateK = Number(el("workspace-lab-candidate-k")?.value || 20);
  setLoading("workspace-lab-output", "运行 Baseline（内置 demo_eval）…");
  try {
    const payload = await runRagLab({
      top_k: topK,
      candidate_k: candidateK,
      configs: [{ config_id: "baseline", top_k: topK, candidate_k: candidateK, use_rerank: true }],
    });
    setOutput("workspace-lab-output", renderLabResults(payload));
    bindLabOutputActions();
  } catch (error) {
    setError("workspace-lab-output", error);
  }
  });
}

export async function runWorkspaceLabFromCases(cases) {
  await withButtonBusy("workspace-run-lab", async () => {
  const topK = Number(el("workspace-lab-top-k")?.value || 5);
  const candidateK = Number(el("workspace-lab-candidate-k")?.value || 20);
  setLoading("workspace-lab-output", "运行自定义 Eval…");
  try {
    const payload = await runRagLab({
      top_k: topK,
      candidate_k: candidateK,
      cases,
      configs: [{ config_id: "custom", top_k: topK, candidate_k: candidateK, use_rerank: true }],
    });
    setOutput("workspace-lab-output", renderLabResults(payload));
    bindLabOutputActions();
  } catch (error) {
    setError("workspace-lab-output", error);
  }
  });
}

export async function runWorkspaceLab() {
  await withButtonBusy("workspace-run-lab", async () => {
  const topK = Number(el("workspace-lab-top-k")?.value || 5);
  const candidateK = Number(el("workspace-lab-candidate-k")?.value || 20);
  setLoading("workspace-lab-output", "运行 RAG Lab...");
  try {
    const payload = await runRagLab({
      top_k: topK,
      candidate_k: candidateK,
      configs: [
        { config_id: "fusion", top_k: topK, candidate_k: candidateK, use_rerank: false },
        { config_id: "rerank", top_k: topK, candidate_k: candidateK, use_rerank: true },
      ],
    });
    setOutput("workspace-lab-output", renderLabResults(payload));
    bindLabOutputActions();
  } catch (error) {
    setError("workspace-lab-output", error);
  }
  });
}

export async function runWorkspaceReview() {
  await withButtonBusy("workspace-run-review", async () => {
  const topic = el("workspace-review-topic")?.value?.trim();
  if (!topic) {
    setOutput("workspace-review-output", `<p class="settings-empty">请输入主题。</p>`);
    return;
  }
  setLoading("workspace-review-output", "生成深度综述...");
  try {
    const review = await runDeepReview({ topic, top_k: 5 });
    setOutput("workspace-review-output", `
      <div class="workspace-stack">
        <article class="workspace-card">
          <div class="workspace-card-head">
            <strong>${escapeHtml(review.topic || topic)}</strong>
            <span>${escapeHtml(String((review.evidence || []).length))} 证据</span>
          </div>
          <p>${escapeHtml(review.overview || "")}</p>
        </article>
        <div class="workspace-subsection">
          <h4>代表论文</h4>
          <ul class="workspace-list">${(review.representative_papers || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
        <div class="workspace-subsection">
          <h4>时间线</h4>
          ${(review.timeline || []).map((item) => `
            <div class="timeline-row">
              <strong>${escapeHtml(String(item.year || ""))}</strong>
              <span>${escapeHtml(item.title || item.paper_id || "")}</span>
            </div>
          `).join("")}
        </div>
        <div class="workspace-subsection">
          <h4>开放问题</h4>
          <ul class="workspace-list">${(review.open_problems || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
      </div>
    `);
  } catch (error) {
    setError("workspace-review-output", error);
  }
  });
}

export async function refreshWorkspaceStatus() {
  await withButtonBusy("workspace-refresh-status", async () => {
  setLoading("workspace-status-output", "读取运行状态...");
  try {
    const status = await getRuntimeStatus();
    const usage = status.usage || {};
    setOutput("workspace-status-output", `
      <div class="workspace-stack">
        <div class="workspace-metrics-row">
          ${renderMiniMetric("文档", status.corpus?.documents ?? "-")}
          ${renderMiniMetric("片段", status.corpus?.passages ?? "-")}
          ${renderMiniMetric("API 调用", usage.total_calls ?? 0)}
        </div>
        <article class="workspace-card">
          <div class="workspace-card-head">
            <strong>${escapeHtml(status.model?.model || "unknown")}</strong>
            <span>${escapeHtml(status.model?.provider || "local")}</span>
          </div>
          <div class="workspace-status-grid">
            <span>Chat</span><strong>${status.model?.chat_enabled ? "启用" : "本地规则"}</strong>
            <span>Embedding</span><strong>${status.model?.embedding_enabled ? status.model.embedding_model : "未启用"}</strong>
            <span>Rerank</span><strong>${status.model?.rerank_enabled ? status.model.rerank_model : "未启用"}</strong>
            <span>Fusion</span><strong>${escapeHtml(status.retrieval?.fusion_method || "hybrid")}</strong>
          </div>
        </article>
      </div>
    `);
  } catch (error) {
    setError("workspace-status-output", error);
  }
  });
}

function activateTab(tabName, { focusTab = false } = {}) {
  document.querySelectorAll(".workspace-tab").forEach((button) => {
    const isActive = button.dataset.workspaceTab === tabName;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
    button.tabIndex = isActive ? 0 : -1;
    if (focusTab && isActive) button.focus();
  });
  document.querySelectorAll(".workspace-view").forEach((view) => {
    const isActive = view.dataset.workspaceView === tabName;
    view.classList.toggle("active", isActive);
    view.hidden = !isActive;
    view.tabIndex = isActive ? 0 : -1;
  });
}

function focusWorkspaceTabByIndex(index, { focusTab = true } = {}) {
  const tabs = [...document.querySelectorAll(".workspace-tab")];
  if (!tabs.length) return;
  const normalized = ((index % tabs.length) + tabs.length) % tabs.length;
  const tabName = tabs[normalized]?.dataset.workspaceTab;
  if (tabName) activateTab(tabName, { focusTab });
}

function handleWorkspaceTabKeydown(event) {
  const tabs = [...document.querySelectorAll(".workspace-tab")];
  const currentIndex = tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
  if (currentIndex < 0) return;

  let nextIndex = currentIndex;
  if (event.key === "ArrowRight") nextIndex = currentIndex + 1;
  else if (event.key === "ArrowLeft") nextIndex = currentIndex - 1;
  else if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = tabs.length - 1;
  else return;

  event.preventDefault();
  focusWorkspaceTabByIndex(nextIndex, { focusTab: true });
  const normalized = ((nextIndex % tabs.length) + tabs.length) % tabs.length;
  const tabName = tabs[normalized]?.dataset.workspaceTab;
  if (tabName === "documents" && cachedDocuments.length === 0) refreshWorkspaceDocuments();
  if (tabName === "status") refreshWorkspaceStatus();
  if (tabName === "evidence") renderLatestEvidence();
}

function revealWorkspacePanel() {
  const panel = el("workspace-panel");
  if (panel) {
    panel.classList.add("workspace-open");
    panel.removeAttribute("inert");
    panel.setAttribute("aria-hidden", "false");
    bindWorkspaceFocusTrap(panel);
    focusWorkspaceCloseButton();
  }
  showWorkspaceScrim(true);
  setWorkspaceShellInert(true);
}

export function openWorkspace() {
  const settingsPanel = document.getElementById("settings-panel");
  const settingsOpen = settingsPanel
    && !settingsPanel.hidden
    && !settingsPanel.classList.contains("settings-panel-closing");
  if (settingsOpen) {
    dismissSettingsPanelAnimated(revealWorkspacePanel);
    return;
  }
  revealWorkspacePanel();
}

export function closeWorkspace() {
  const panel = el("workspace-panel");
  if (panel) {
    panel.classList.remove("workspace-open");
    panel.setAttribute("inert", "");
    panel.setAttribute("aria-hidden", "true");
    removeWorkspaceFocusTrap();
  }
  showWorkspaceScrim(false);
  setWorkspaceShellInert(false);
  focusWorkspaceToggle();
}

export function initWorkspace() {
  const close = el("workspace-close");
  close?.addEventListener("click", closeWorkspace);
  el("workspace-scrim")?.addEventListener("click", closeWorkspace);

  const tablist = document.querySelector(".workspace-tabs");
  tablist?.addEventListener("keydown", handleWorkspaceTabKeydown);

  document.querySelectorAll(".workspace-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateTab(button.dataset.workspaceTab);
      if (button.dataset.workspaceTab === "documents" && cachedDocuments.length === 0) refreshWorkspaceDocuments();
      if (button.dataset.workspaceTab === "status") refreshWorkspaceStatus();
      if (button.dataset.workspaceTab === "evidence") renderLatestEvidence();
    });
  });

  el("workspace-load-evidence")?.addEventListener("click", renderLatestEvidence);
  el("workspace-refresh-documents")?.addEventListener("click", refreshWorkspaceDocuments);
  el("workspace-run-lab-baseline")?.addEventListener("click", runWorkspaceLabBaseline);
  el("workspace-run-lab")?.addEventListener("click", runWorkspaceLab);
  el("workspace-run-reading")?.addEventListener("click", () => renderReadingBrief());
  el("workspace-run-review")?.addEventListener("click", runWorkspaceReview);
  el("workspace-refresh-status")?.addEventListener("click", refreshWorkspaceStatus);

  el("workspace-delete-all-documents")?.addEventListener("click", async () => {
    const imported = cachedDocuments.filter((d) => d.imported);
    if (!imported.length) return;
    const confirmed = await confirmAction({
      title: `删除全部导入文档？`,
      message: `将从知识库移除 ${imported.length} 个导入文档，无法恢复。`,
      confirmText: "全部删除",
      tone: "danger",
    });
    if (!confirmed) return;
    setLoading("workspace-documents-output", `删除中（共 ${imported.length} 个）...`);
    let failed = 0;
    for (const doc of imported) {
      try {
        await deleteDocument(doc.paper_id);
      } catch {
        failed++;
      }
    }
    if (failed > 0) {
      setError("workspace-documents-output", new Error(`删除完成，${failed} 个失败。`));
    }
    await refreshWorkspaceDocuments();
  });

  const docOutput = el("workspace-documents-output");
  docOutput?.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.id === "workspace-documents-back") {
      await refreshWorkspaceDocuments();
      return;
    }
    const paperId = button.dataset.paperId;
    if (!paperId) return;
    if (button.classList.contains("document-detail-button")) {
      await showDocumentDetail(paperId);
      return;
    }
    if (button.classList.contains("document-brief-button")) {
      activateTab("reading");
      const select = el("workspace-reading-select");
      if (select) select.value = paperId;
      await renderReadingBrief(paperId);
      return;
    }
    if (button.classList.contains("document-delete-button")) {
      const confirmed = await confirmAction({
        title: "删除导入文档？",
        message: "该文档会从本地知识库中移除。",
        confirmText: "删除",
        tone: "danger",
      });
      if (!confirmed) return;
      try {
        await deleteDocument(paperId);
        await refreshWorkspaceDocuments();
      } catch (error) {
        setError("workspace-documents-output", error);
      }
    }
  });

  refreshWorkspaceDocuments();
  refreshWorkspaceStatus();
  const panel = el("workspace-panel");
  if (panel && !panel.classList.contains("workspace-open")) {
    panel.setAttribute("inert", "");
    panel.setAttribute("aria-hidden", "true");
  }
}
