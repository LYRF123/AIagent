const modeButtons = Array.from(document.querySelectorAll(".mode-button"));
const modeFields = Array.from(document.querySelectorAll("[data-mode]"));
const presetButtons = Array.from(document.querySelectorAll(".preset-button"));
const utilityNavButtons = Array.from(document.querySelectorAll("[data-utility-panel-target]"));
const utilityPanels = Array.from(document.querySelectorAll("[data-utility-panel]"));
const form = document.getElementById("agent-form");
const uploadForm = document.getElementById("upload-form");
const uploadFile = document.getElementById("upload-file");
const refreshDocumentsButton = document.getElementById("refresh-documents");
const submitButton = document.getElementById("submit-button");
const healthButton = document.getElementById("health-button");
const newSessionButton = document.getElementById("new-session");
const openToolsButton = document.getElementById("open-tools");
const closeUtilityButton = document.getElementById("close-utility");
const strictGroundedInput = document.getElementById("strict-grounded");
const statusPill = document.getElementById("status-pill");
const sessionsOutput = document.getElementById("sessions-output");
const summaryOutput = document.getElementById("summary-output");
const detailOutput = document.getElementById("detail-output");
const documentsOutput = document.getElementById("documents-output");
const jsonOutput = document.getElementById("json-output");
const modeBadge = document.getElementById("mode-badge");
const utilityDrawer = document.getElementById("utility-drawer");
const utilityTitle = document.getElementById("utility-title");

let currentMode = "ask";
let currentSessionId = "";
let currentUtility = "presets";

const modeLabels = {
  ask: "问答",
  search: "检索",
  compare: "对比",
  review: "综述",
  evaluate: "评测",
};

const sectionLabels = {
  summary: "摘要",
  methods: "方法",
  findings: "结论",
  limitations: "局限",
  topics: "主题词",
};

const utilityLabels = {
  presets: "快捷示例",
  import: "文档导入",
  documents: "知识库文件",
  json: "原始 JSON",
};

function setStatus(text, kind = "idle") {
  statusPill.textContent = text;
  statusPill.className = `status-pill ${kind}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTimestamp(value) {
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

function showUtilityPanel(target) {
  currentUtility = target;
  utilityTitle.textContent = utilityLabels[target] || "工具面板";
  utilityNavButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.utilityPanelTarget === target);
  });
  utilityPanels.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.utilityPanel !== target);
  });
}

function openUtilityDrawer(target = currentUtility || "presets") {
  utilityDrawer.classList.remove("hidden");
  if (openToolsButton) {
    openToolsButton.classList.add("active");
  }
  showUtilityPanel(target);
}

function closeUtilityDrawer() {
  utilityDrawer.classList.add("hidden");
  if (openToolsButton) {
    openToolsButton.classList.remove("active");
  }
}

function showMode(mode) {
  currentMode = mode;
  modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  modeFields.forEach((field) => {
    field.classList.toggle("hidden", field.dataset.mode !== mode);
  });
  submitButton.textContent = `运行${modeLabels[mode]}`;
  modeBadge.textContent = `当前模式：${modeLabels[mode]}`;
}

function renderEmptySummary(title, text) {
  summaryOutput.innerHTML = `
    <div class="empty-state">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function renderList(title, items) {
  const rows = (items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `
    <section>
      <h4>${escapeHtml(title)}</h4>
      <ul>${rows || "<li>无</li>"}</ul>
    </section>
  `;
}

function renderTrace(trace) {
  if (!trace || trace.length === 0) {
    return `<div class="detail-block"><h4>调用轨迹</h4><p class="block-note">没有轨迹信息。</p></div>`;
  }
  const rows = trace.map((item) => `
    <div class="trace-item">
      <header>
        <strong>${escapeHtml(item.tool)}</strong>
      </header>
      <p class="block-note">输入：${escapeHtml(item.input || "")}</p>
      <p>${escapeHtml(item.output || "")}</p>
    </div>
  `).join("");
  return `<div class="detail-block"><h4>调用轨迹</h4>${rows}</div>`;
}

function renderEvidence(evidence) {
  if (!evidence || evidence.length === 0) {
    return `<div class="detail-block"><h4>证据片段</h4><p class="block-note">当前结果没有返回证据。</p></div>`;
  }
  const rows = evidence.map((item) => `
    <div class="evidence-item">
      <header>
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p class="block-note">paper_id: ${escapeHtml(item.paper_id)}</p>
        </div>
        <div class="score-badge">分数 ${escapeHtml(item.score)}</div>
      </header>
      <div class="evidence-section">${escapeHtml(sectionLabels[item.section] || item.section)}</div>
      <p>${escapeHtml(item.text)}</p>
    </div>
  `).join("");
  return `<div class="detail-block"><h4>证据片段</h4>${rows}</div>`;
}

function renderHistory(history) {
  if (!history || history.length === 0) {
    return `<div class="detail-block"><h4>会话历史</h4><p class="block-note">当前没有保存的会话历史。</p></div>`;
  }
  const rows = history.map((item) => `
    <div class="message-item ${escapeHtml(item.role)}">
      <div class="message-role">${item.role === "user" ? "用户" : "助手"}</div>
      <p>${escapeHtml(item.content || "")}</p>
    </div>
  `).join("");
  return `<div class="detail-block"><h4>会话历史</h4><div class="message-list">${rows}</div></div>`;
}

function renderSessionPanel(session) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>${escapeHtml(session.title || "新会话")}</h3>
      <p class="summary-main">共 ${escapeHtml(session.turn_count || 0)} 轮问答</p>
      <p class="summary-meta">更新时间：${escapeHtml(formatTimestamp(session.updated_at || ""))}</p>
    </div>
    <div class="summary-block">
      <h3>使用方式</h3>
      <p class="summary-subtext">继续在当前模式里提问，新结果会自动追加到这个会话。</p>
    </div>
  `;
  detailOutput.innerHTML = `
    ${renderHistory(session.messages)}
    <div class="detail-block">
      <h4>当前限制</h4>
      <p class="block-note">历史会话只保存消息内容；证据片段和调用轨迹会在新的问答结果里展示。</p>
    </div>
  `;
  jsonOutput.textContent = JSON.stringify(session, null, 2);
}

function renderStreamingAskState(answer, sessionTitle = "新会话") {
  const visibleAnswer = answer || "正在生成回答...";
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>回答生成中</h3>
      <p class="summary-main">${escapeHtml(visibleAnswer)}</p>
      <p class="summary-meta">会话标题：${escapeHtml(sessionTitle || "新会话")}</p>
    </div>
    <div class="summary-block">
      <h3>流式输出</h3>
      <p class="summary-subtext">回答正在逐段返回；最终证据、轨迹和完整 JSON 会在生成结束后补齐。</p>
    </div>
  `;
  detailOutput.innerHTML = `
    <div class="detail-block">
      <h4>实时输出</h4>
      <p>${escapeHtml(visibleAnswer)}</p>
      <p class="block-note">系统会在流结束后补充证据片段、调用轨迹和完整会话历史。</p>
    </div>
  `;
}

function renderSessions(items) {
  if (!items || items.length === 0) {
    sessionsOutput.innerHTML = `<p class="empty-note">还没有会话。</p>`;
    return;
  }

  sessionsOutput.innerHTML = items.map((item) => `
    <div class="session-card ${item.session_id === currentSessionId ? "active" : ""}">
      <button class="session-open" data-session-id="${escapeHtml(item.session_id)}" type="button">
        <strong>${escapeHtml(item.title || "新会话")}</strong>
        <p class="block-note">${escapeHtml(item.preview || "还没有历史消息。")}</p>
        <p class="session-meta">${escapeHtml(`${item.turn_count || 0} 轮 · ${formatTimestamp(item.updated_at || "")}`)}</p>
      </button>
      <button class="danger-button compact-button delete-session" data-session-id="${escapeHtml(item.session_id)}" type="button">删除</button>
    </div>
  `).join("");

  document.querySelectorAll(".session-open").forEach((button) => {
    button.addEventListener("click", async () => {
      const sessionId = button.dataset.sessionId;
      if (!sessionId) {
        return;
      }
      await loadSession(sessionId);
    });
  });

  document.querySelectorAll(".delete-session").forEach((button) => {
    button.addEventListener("click", async () => {
      const sessionId = button.dataset.sessionId;
      if (!sessionId) {
        return;
      }
      if (!window.confirm("确认删除这个会话吗？历史消息会一起清空。")) {
        return;
      }
      await deleteSession(sessionId);
    });
  });
}

function renderDocuments(items) {
  if (!items || items.length === 0) {
    documentsOutput.innerHTML = `<p class="empty-note">还没有导入文件。</p>`;
    return;
  }
  documentsOutput.innerHTML = items.map((item) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p class="block-note">paper_id: ${escapeHtml(item.paper_id)}</p>
        </div>
        <button class="danger-button compact-button delete-document" data-paper-id="${escapeHtml(item.paper_id)}" type="button">删除</button>
      </header>
      <p class="block-note">文件：${escapeHtml(item.file_name || "")}</p>
      <p class="block-note">来源：${escapeHtml(item.source_url || "")}</p>
      <p>${escapeHtml(item.summary_preview || "")}</p>
    </div>
  `).join("");

  document.querySelectorAll(".delete-document").forEach((button) => {
    button.addEventListener("click", async () => {
      const paperId = button.dataset.paperId;
      if (!paperId) {
        return;
      }
      if (!window.confirm("确认删除这份文档吗？删除后会同步刷新知识库索引。")) {
        return;
      }
      await deleteDocument(paperId);
    });
  });
}

async function refreshDocuments() {
  try {
    const response = await fetch("/documents");
    const data = await response.json();
    renderDocuments(data.items || []);
  } catch {
    documentsOutput.innerHTML = `<p class="empty-note">文档列表加载失败。</p>`;
  }
}

async function refreshSessions(nextSessionId = currentSessionId) {
  try {
    const response = await fetch("/sessions");
    const data = await response.json();
    const items = data.items || [];
    if (items.some((item) => item.session_id === nextSessionId)) {
      currentSessionId = nextSessionId;
    } else if (!items.some((item) => item.session_id === currentSessionId)) {
      currentSessionId = "";
    }
    renderSessions(items);
  } catch {
    sessionsOutput.innerHTML = `<p class="empty-note">会话列表加载失败。</p>`;
  }
}

async function loadSession(sessionId) {
  setStatus("正在加载会话...", "loading");
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `加载失败：${response.status}`);
    }
    currentSessionId = sessionId;
    renderSessionPanel(data);
    await refreshSessions(sessionId);
    setStatus("会话已加载", "success");
  } catch (error) {
    setStatus("会话加载失败", "error");
    renderEmptySummary("会话加载失败", error.message || "无法读取会话详情");
    detailOutput.innerHTML = `<p class="empty-note">请刷新会话列表后重试。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function createSession() {
  setStatus("正在创建会话...", "loading");
  try {
    const response = await fetch("/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `创建失败：${response.status}`);
    }
    currentSessionId = data.session.session_id;
    renderSessionPanel(data.session);
    renderSessions(data.sessions || []);
    setStatus("已创建新会话", "success");
  } catch (error) {
    setStatus("创建失败", "error");
    renderEmptySummary("创建会话失败", error.message || "会话创建失败");
    detailOutput.innerHTML = `<p class="empty-note">请稍后重试。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function deleteSession(sessionId) {
  setStatus("正在删除会话...", "loading");
  try {
    const response = await fetch("/delete-session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `删除失败：${response.status}`);
    }
    if (currentSessionId === sessionId) {
      currentSessionId = "";
      renderEmptySummary("会话已删除", "可以新建会话，或者直接提问自动生成新的会话。");
      detailOutput.innerHTML = `<p class="empty-note">当前没有选中的会话。</p>`;
      jsonOutput.textContent = JSON.stringify(data, null, 2);
    }
    renderSessions(data.sessions || []);
    setStatus("会话已删除", "success");
  } catch (error) {
    setStatus("删除失败", "error");
    renderEmptySummary("删除会话失败", error.message || "会话删除失败");
    detailOutput.innerHTML = `<p class="empty-note">请稍后重试。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

function renderSearchSummary(data) {
  if (!data || data.length === 0) {
    renderEmptySummary("没有检索结果", "可以换一个更具体的关键词，或者把 Top K 调大一点。");
    detailOutput.innerHTML = `<p class="empty-note">检索为空时，这里没有更多细节。</p>`;
    return;
  }

  const top = data[0];
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>最相关结果</h3>
      <p class="summary-main">${escapeHtml(top.title)}</p>
      <p class="summary-meta">paper_id: ${escapeHtml(top.paper_id)} · 分数 ${escapeHtml(top.score)}</p>
    </div>
    <div class="summary-block">
      <h3>可快速阅读的信息</h3>
      <p class="summary-subtext">先看标题和 highlights，再决定是否继续问答或做对比。</p>
    </div>
  `;

  const cards = data.map((item) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p class="block-note">paper_id: ${escapeHtml(item.paper_id)}</p>
        </div>
        <div class="score-badge">分数 ${escapeHtml(item.score)}</div>
      </header>
      <div>
        <h4>关键片段</h4>
        <ul>${(item.highlights || []).map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>
      </div>
    </div>
  `).join("");

  detailOutput.innerHTML = cards;
}

function renderAskSummary(data) {
  const helperTitle = data.insufficient_evidence ? "证据状态" : "快速判断";
  const helperText = data.insufficient_evidence
    ? "当前问题没有检索到足够证据，系统已阻止自由生成回答。你可以换关键词、缩小问题范围，或关闭严格证据模式。"
    : "如果回答里提到了具体论文和机制，再到下方查看证据与轨迹。";
  summaryOutput.innerHTML = `
    <div class="summary-block primary ${data.insufficient_evidence ? "warning" : ""}">
      <h3>回答</h3>
      <p class="summary-main">${escapeHtml(data.answer || "")}</p>
      <p class="summary-meta">会话标题：${escapeHtml(data.session_title || "未命名会话")}</p>
    </div>
    <div class="summary-block">
      <h3>${escapeHtml(helperTitle)}</h3>
      <p class="summary-subtext">${escapeHtml(helperText)}</p>
    </div>
  `;
  detailOutput.innerHTML = `${renderHistory(data.history)}${renderEvidence(data.evidence)}${renderTrace(data.trace)}`;
}

function renderCompareSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>对比结论</h3>
      <p class="summary-main">${escapeHtml(data.narrative || "")}</p>
    </div>
    <div class="summary-block">
      <h3>阅读建议</h3>
      <p class="summary-subtext">先看总述，再看每篇论文的“方法 / 结论 / 局限”。</p>
    </div>
  `;

  const cards = (data.rows || []).map((row) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(row.title)}</strong>
          <p class="block-note">${escapeHtml(row.paper_id)} · ${escapeHtml(row.year)}</p>
        </div>
      </header>
      ${renderList("方法", row.methods)}
      ${renderList("结论", row.findings)}
      ${renderList("局限性", row.limitations)}
    </div>
  `).join("");

  detailOutput.innerHTML = `${cards}${renderTrace(data.trace)}`;
}

function renderReviewSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>综述结论</h3>
      <p class="summary-main">${escapeHtml(data.overview || "")}</p>
    </div>
    <div class="summary-block">
      <h3>适合怎么用</h3>
      <p class="summary-subtext">先看趋势和代表论文，再参考阅读顺序和开放问题。</p>
    </div>
  `;

  detailOutput.innerHTML = `
    <div class="review-grid">
      ${renderList("趋势", data.trends)}
      ${renderList("代表论文", data.representative_papers)}
      ${renderList("阅读顺序", data.reading_order)}
      ${renderList("开放问题", data.open_problems)}
    </div>
    ${renderTrace(data.trace)}
  `;
}

function renderEvaluateSummary(data) {
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>评测指标</h3>
      <p class="summary-main">paper 命中率 ${escapeHtml(data.paper_hit_rate)} · 关键词命中率 ${escapeHtml(data.keyword_hit_rate)}</p>
      <p class="summary-meta">通过 ${escapeHtml(data.passed_cases)} / ${escapeHtml(data.num_cases)} · 失败 ${escapeHtml(data.failed_cases)} · 平均回答长度 ${escapeHtml(data.avg_answer_length)}</p>
    </div>
    <div class="summary-block">
      <h3>怎么看结果</h3>
      <p class="summary-subtext">优先看失败样例，它们最适合拿来做 bad case 分析和后续优化。</p>
    </div>
  `;

  const failures = (data.failures || []).map((item) => `
    <div class="paper-card">
      <header>
        <div>
          <strong>${escapeHtml(item.case_id)}</strong>
          <p class="block-note">问题：${escapeHtml(item.question)}</p>
        </div>
      </header>
      <p class="block-note">命中情况：paper=${escapeHtml(item.paper_hit)} · keyword=${escapeHtml(item.keyword_hit)}</p>
      <p class="block-note">期望论文：${escapeHtml((item.expected_paper_ids || []).join(", "))}</p>
      <p class="block-note">实际引用：${escapeHtml((item.cited_ids || []).join(", "))}</p>
      <p>${escapeHtml(item.answer || "")}</p>
    </div>
  `).join("");

  detailOutput.innerHTML = failures || `<div class="detail-block"><h4>失败样例</h4><p class="block-note">当前评测集全部通过，没有失败样例。</p></div>`;
}

function renderResult(mode, data) {
  if (mode === "search") {
    renderSearchSummary(data);
    return;
  }
  if (mode === "ask") {
    renderAskSummary(data);
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

function buildPayload(mode) {
  const topK = Number(document.getElementById("top-k").value || 5);
  if (mode === "search") {
    return {
      endpoint: "/search",
      payload: {
        query: document.getElementById("search-query").value,
        top_k: topK,
      },
    };
  }
  if (mode === "ask") {
    return {
      endpoint: "/ask",
      payload: {
        question: document.getElementById("ask-question").value,
        top_k: topK,
        session_id: currentSessionId || undefined,
        strict_grounded: strictGroundedInput.checked,
      },
    };
  }
  if (mode === "compare") {
    return {
      endpoint: "/compare",
      payload: {
        paper_ids: document.getElementById("compare-ids").value.split(/\s+/).filter(Boolean),
        focus: document.getElementById("compare-focus").value,
      },
    };
  }
  if (mode === "review") {
    return {
      endpoint: "/review",
      payload: {
        topic: document.getElementById("review-topic").value,
        top_k: topK,
      },
    };
  }
  return {
    endpoint: "/evaluate",
    payload: {
      top_k: topK,
    },
  };
}

async function readEventStream(response, onEvent) {
  if (!response.body) {
    throw new Error("当前浏览器不支持流式响应读取。");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  function processBlock(block) {
    if (!block.trim()) {
      return;
    }
    let eventType = "message";
    const dataLines = [];
    block.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    });
    const rawData = dataLines.join("\n");
    const parsed = rawData ? JSON.parse(rawData) : {};
    onEvent(eventType, parsed);
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      processBlock(block);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      if (buffer.trim()) {
        processBlock(buffer);
      }
      break;
    }
  }
}

async function runAskModeStream(payload) {
  let sessionTitle = "新会话";
  let streamedAnswer = "";
  let finalPayload = null;
  let streamError = null;

  setStatus("正在流式生成回答...", "loading");
  renderStreamingAskState(streamedAnswer, sessionTitle);
  jsonOutput.textContent = JSON.stringify({ status: "streaming", question: payload.question }, null, 2);

  const response = await fetch("/ask-stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || `请求失败：${response.status}`);
  }

  await readEventStream(response, (eventType, data) => {
    if (eventType === "session") {
      currentSessionId = data.session_id || currentSessionId;
      sessionTitle = data.session_title || sessionTitle;
      renderStreamingAskState(streamedAnswer, sessionTitle);
      return;
    }
    if (eventType === "chunk") {
      streamedAnswer += data.delta || "";
      renderStreamingAskState(streamedAnswer, sessionTitle);
      jsonOutput.textContent = JSON.stringify(
        {
          status: "streaming",
          session_id: currentSessionId || undefined,
          answer_preview: streamedAnswer,
        },
        null,
        2,
      );
      return;
    }
    if (eventType === "final") {
      finalPayload = data;
      return;
    }
    if (eventType === "error") {
      streamError = new Error(data.error || "流式输出失败");
    }
  });

  if (streamError) {
    throw streamError;
  }
  if (!finalPayload) {
    throw new Error("流式请求提前结束，未收到最终结果。");
  }

  setStatus("问答完成", "success");
  renderAskSummary(finalPayload);
  jsonOutput.textContent = JSON.stringify(finalPayload, null, 2);
  if (finalPayload.session_id) {
    currentSessionId = finalPayload.session_id;
    await refreshSessions(finalPayload.session_id);
  }
}

async function runMode(mode) {
  const { endpoint, payload } = buildPayload(mode);
  if (mode === "ask") {
    try {
      await runAskModeStream(payload);
    } catch (error) {
      setStatus("请求失败", "error");
      renderEmptySummary("请求失败", error.message || "发生未知错误");
      detailOutput.innerHTML = `<p class="empty-note">请检查输入内容或后端服务状态。</p>`;
      jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
    }
    return;
  }

  setStatus(`正在运行${modeLabels[mode]}...`, "loading");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `请求失败：${response.status}`);
    }
    setStatus(`${modeLabels[mode]}完成`, "success");
    renderResult(mode, data);
    jsonOutput.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    setStatus("请求失败", "error");
    renderEmptySummary("请求失败", error.message || "发生未知错误");
    detailOutput.innerHTML = `<p class="empty-note">请检查输入内容或后端服务状态。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

async function importDocument(file) {
  const body = new FormData();
  body.append("file", file);
  setStatus("正在导入文件...", "loading");
  const response = await fetch("/import-document", {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `导入失败：${response.status}`);
  }
  setStatus("导入完成", "success");
  summaryOutput.innerHTML = `
    <div class="summary-block primary">
      <h3>导入成功</h3>
      <p class="summary-main">${escapeHtml(data.document.title)}</p>
      <p class="summary-meta">paper_id: ${escapeHtml(data.document.paper_id)}</p>
    </div>
    <div class="summary-block">
      <h3>接下来可以做什么</h3>
      <p class="summary-subtext">现在你可以直接在问答或检索里针对这份新文档提问了。</p>
    </div>
  `;
  detailOutput.innerHTML = `
    <div class="detail-block">
      <h4>导入结果</h4>
      <p>${escapeHtml(data.message || "")}</p>
      <p class="block-note">当前已导入文档数：${escapeHtml(data.document.imported_count || 0)}</p>
      <p>${escapeHtml(data.document.summary_preview || "")}</p>
    </div>
  `;
  jsonOutput.textContent = JSON.stringify(data, null, 2);
  renderDocuments(data.documents || []);
  openUtilityDrawer("documents");
}

async function deleteDocument(paperId) {
  setStatus("正在删除文档...", "loading");
  try {
    const response = await fetch("/delete-document", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paper_id: paperId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `删除失败：${response.status}`);
    }
    setStatus("删除完成", "success");
    summaryOutput.innerHTML = `
      <div class="summary-block primary">
        <h3>删除成功</h3>
        <p class="summary-main">${escapeHtml(data.document.title)}</p>
        <p class="summary-meta">剩余文档数：${escapeHtml(data.document.remaining_count)}</p>
      </div>
    `;
    detailOutput.innerHTML = `
      <div class="detail-block">
        <h4>删除结果</h4>
        <p>${escapeHtml(data.message || "")}</p>
      </div>
    `;
    jsonOutput.textContent = JSON.stringify(data, null, 2);
    renderDocuments(data.documents || []);
    openUtilityDrawer("documents");
  } catch (error) {
    setStatus("删除失败", "error");
    renderEmptySummary("删除失败", error.message || "文档删除失败");
    detailOutput.innerHTML = `<p class="empty-note">请稍后重试，或先刷新文档列表。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
}

function applyPreset(name) {
  if (name === "ask-react") {
    showMode("ask");
    document.getElementById("ask-question").value = "ReAct 是如何把推理和工具调用结合起来的？";
    closeUtilityDrawer();
    return;
  }
  if (name === "ask-model") {
    showMode("ask");
    document.getElementById("ask-question").value = "你是什么模型？";
    closeUtilityDrawer();
    return;
  }
  if (name === "search-rag") {
    showMode("search");
    document.getElementById("search-query").value = "self reflection retrieval";
    closeUtilityDrawer();
    return;
  }
  if (name === "compare-agent") {
    showMode("compare");
    document.getElementById("compare-ids").value = "react toolformer";
    document.getElementById("compare-focus").value = "方法、结论和局限性";
    closeUtilityDrawer();
    return;
  }
  if (name === "review-agent") {
    showMode("review");
    document.getElementById("review-topic").value = "multi agent software development";
    closeUtilityDrawer();
    return;
  }
  showMode("evaluate");
  closeUtilityDrawer();
}

modeButtons.forEach((button) => {
  button.addEventListener("click", () => showMode(button.dataset.mode));
});

presetButtons.forEach((button) => {
  button.addEventListener("click", () => applyPreset(button.dataset.preset));
});

utilityNavButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.utilityPanelTarget;
    if (target) {
      showUtilityPanel(target);
    }
  });
});

if (openToolsButton) {
  openToolsButton.addEventListener("click", () => {
    if (utilityDrawer.classList.contains("hidden")) {
      openUtilityDrawer(currentUtility || "presets");
    } else {
      closeUtilityDrawer();
    }
  });
}

if (closeUtilityButton) {
  closeUtilityButton.addEventListener("click", () => {
    closeUtilityDrawer();
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runMode(currentMode);
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = uploadFile.files?.[0];
  if (!file) {
    setStatus("请先选择文件", "error");
    return;
  }
  try {
    await importDocument(file);
    uploadForm.reset();
  } catch (error) {
    setStatus("导入失败", "error");
    renderEmptySummary("导入失败", error.message || "文件导入失败");
    detailOutput.innerHTML = `<p class="empty-note">请确认文件格式为 PDF、DOCX 或 TXT。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
});

if (refreshDocumentsButton) {
  refreshDocumentsButton.addEventListener("click", async () => {
    setStatus("正在刷新文档列表...", "loading");
    await refreshDocuments();
    openUtilityDrawer("documents");
    setStatus("文档列表已刷新", "success");
  });
}

if (newSessionButton) {
  newSessionButton.addEventListener("click", async () => {
    await createSession();
  });
}

healthButton.addEventListener("click", async () => {
  setStatus("正在检查服务...", "loading");
  try {
    const response = await fetch("/health");
    const data = await response.json();
    setStatus("服务正常", "success");
    summaryOutput.innerHTML = `
      <div class="summary-block primary">
        <h3>健康检查</h3>
        <p class="summary-main">服务可访问，状态正常。</p>
      </div>
    `;
    detailOutput.innerHTML = `<div class="detail-block"><h4>返回内容</h4><p>${escapeHtml(JSON.stringify(data))}</p></div>`;
    jsonOutput.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    setStatus("健康检查失败", "error");
    renderEmptySummary("服务不可用", error.message || "请检查本地服务");
    detailOutput.innerHTML = `<p class="empty-note">如果服务没启动，请重新运行 research_agent.server。</p>`;
    jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
  }
});

showMode(currentMode);
showUtilityPanel(currentUtility);
closeUtilityDrawer();
refreshDocuments();
refreshSessions();
