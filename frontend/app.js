import {
  appShell, sidebar, sidebarToggle,
  sessionsOutput, newChatButton, clearChatButton,
  settingsButton,
  workspaceToggle,
  chatMessages, welcomeScreen, chatForm, chatInput, chatSubmit, chatStop,
  getCurrentSessionId, setCurrentSessionId,
  getIsSubmitting, setIsSubmitting,
  compactSessionSidebarQuery,
  saveDraft, loadDraft, clearDraft,
  loadSettings, saveSettings,
} from "./state.js";

import { refreshSessions, loadSession, createSession, deleteSession, uploadDocument, listDocuments, getModelSettings, updateModelSettings, listAvailableModels } from "./api.js";
import { runChatStream, abortChatStream, getLastStreamQuestion } from "./stream.js";
import { initWorkspace, renderLatestEvidence, refreshWorkspaceDocuments, refreshWorkspaceStatus } from "./workspace.js";
import {
  toggleWelcomeScreen, scrollToBottom, renderSessionHistory,
} from "./render/chat.js";
import { escapeHtml } from "./render/escape.js";

import {
  shouldStartWithSessionSidebarOpen, setSessionSidebarOpen,
  getStoredSessionSidebarState, closeSessionSidebarOnSmallScreen,
} from "./handlers/sidebar.js";
import { confirmAction } from "./confirm.js";

if (chatForm) {
  chatForm.setAttribute("action", "javascript:void(0)");
}

let appSettings = loadSettings();
let settingsCloseTimer = null;

function mergeModelProfiles(localProfiles = [], remoteProfiles = []) {
  const merged = [];
  const seen = new Set();
  [...remoteProfiles, ...localProfiles].forEach((profile) => {
    const id = profile.id || `${profile.provider}|${profile.base_url}|${profile.model}`;
    if (!id || seen.has(id)) return;
    seen.add(id);
    merged.push({ ...profile, id });
  });
  return merged;
}

function activeProfileId() {
  return appSettings.activeProfileId || "";
}

function profileDisplayName(profile) {
  return profile.name || `${profile.model || "未命名模型"} · ${profile.provider || "provider"}`;
}

function fillModelFields(panel, profile) {
  panel.querySelector("#settings-provider").value = profile.provider || "dashscope";
  panel.querySelector("#settings-base-url").value = profile.base_url || "";
  showModelTextInput(panel, profile.model || "");
  syncProviderFields(panel);
}

function renderModelProfiles(panel) {
  const list = panel.querySelector("#settings-model-profiles");
  if (!list) return;
  const profiles = appSettings.modelProfiles || [];
  if (!profiles.length) {
    list.innerHTML = `<p class="settings-empty">保存模型配置后会出现在这里。</p>`;
    return;
  }
  const activeId = activeProfileId();
  list.innerHTML = profiles.map((profile) => {
    const isActive = Boolean(activeId && profile.id === activeId);
    return `
      <div class="settings-profile ${isActive ? "active" : ""}" data-profile-id="${escapeHtml(profile.id || "")}">
        <div class="settings-profile-main">
          <strong>${escapeHtml(profileDisplayName(profile))}</strong>
          <span>${escapeHtml(profile.model || "")}</span>
          <small>${escapeHtml(profile.base_url || "DashScope 默认地址")} · ${escapeHtml(profile.api_key_masked || "Key 已保存")}</small>
        </div>
        <button class="ghost-button compact-button settings-profile-use" type="button">${isActive ? "当前" : "切换"}</button>
      </div>
    `;
  }).join("");
}

function getSelectedModel(panel) {
  const modelSelect = panel.querySelector("#settings-model-select");
  const modelInput = panel.querySelector("#settings-model");
  return (modelSelect && !modelSelect.hidden ? modelSelect.value : modelInput?.value || "").trim();
}

function showModelTextInput(panel, value = "") {
  const modelSelect = panel.querySelector("#settings-model-select");
  const modelInput = panel.querySelector("#settings-model");
  if (modelSelect) {
    modelSelect.hidden = true;
  }
  if (modelInput) {
    modelInput.hidden = false;
    if (value) {
      modelInput.value = value;
    }
  }
}

function syncProviderFields(panel) {
  const provider = panel.querySelector("#settings-provider")?.value || "dashscope";
  const baseUrlGroup = panel.querySelector("#settings-base-url-group");
  const fetchButton = panel.querySelector("#settings-fetch-models");
  if (baseUrlGroup) {
    baseUrlGroup.hidden = provider !== "openai_compatible";
  }
  if (fetchButton) {
    fetchButton.hidden = provider !== "openai_compatible";
  }
  showModelTextInput(panel);
}

function showToast(message, tone = "info") {
  let toast = document.getElementById("app-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "app-toast";
    toast.className = "app-toast";
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add("app-toast-visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.classList.remove("app-toast-visible");
  }, 2400);
}

function renderDocumentList(items) {
  const output = document.getElementById("settings-documents");
  if (!output) return;
  if (!items || items.length === 0) {
    output.innerHTML = `<p class="settings-empty">还没有导入文档。</p>`;
    return;
  }
  output.innerHTML = items.map((item) => `
    <div class="settings-document">
      <strong>${escapeHtml(item.title || item.file_name || item.paper_id || "未命名文档")}</strong>
      <span>${escapeHtml(item.file_name || item.source_label || item.paper_id || "")}</span>
    </div>
  `).join("");
}

async function refreshDocumentList() {
  const output = document.getElementById("settings-documents");
  if (output) output.innerHTML = `<p class="settings-empty">读取中...</p>`;
  try {
    const data = await listDocuments();
    renderDocumentList(data.items || []);
  } catch (err) {
    if (output) output.innerHTML = `<p class="settings-empty">文档列表读取失败。</p>`;
    console.warn("读取文档列表失败:", err);
  }
}

function ensureSettingsPanel() {
  let panel = document.getElementById("settings-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "settings-panel";
    panel.className = "settings-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="settings-card" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div class="settings-head">
          <div>
            <p class="panel-kicker">设置</p>
            <h2 id="settings-title">模型 &amp; 检索</h2>
          </div>
          <button id="settings-close" class="settings-close" type="button" aria-label="关闭设置">×</button>
        </div>
        <div class="settings-section">
          <h3>模型配置</h3>
          <div class="settings-grid">
            <label class="settings-field">
              <span>配置名称</span>
              <input id="settings-profile-name" type="text" placeholder="我的 GPT / Qwen" />
            </label>
            <label class="settings-field">
              <span>提供商</span>
              <select id="settings-provider">
                <option value="dashscope">DashScope (阿里云)</option>
                <option value="openai_compatible">OpenAI 兼容接口</option>
              </select>
            </label>
            <label class="settings-field">
              <span>API Key</span>
              <input id="settings-api-key" type="password" placeholder="sk-..." autocomplete="off" />
            </label>
            <label class="settings-field" id="settings-base-url-group" hidden>
              <span>Base URL</span>
              <input id="settings-base-url" type="text" placeholder="https://api.openai.com/v1" />
            </label>
            <label class="settings-field" id="settings-model-group">
              <span>模型</span>
              <div style="display:flex;gap:6px;align-items:center;">
                <select id="settings-model-select" style="flex:1;min-width:0;"></select>
                <input id="settings-model" type="text" placeholder="qwen-plus" style="flex:1;min-width:0;" />
                <button id="settings-fetch-models" class="ghost-button compact-button" type="button" style="white-space:nowrap;">获取模型</button>
              </div>
            </label>
          </div>
          <div id="settings-model-status" class="settings-model-status"></div>
          <div class="settings-profile-block">
            <div class="settings-subhead">
              <h3>已保存模型</h3>
              <span>点击切换配置</span>
            </div>
            <div id="settings-model-profiles" class="settings-profiles"></div>
          </div>
        </div>
        <div class="settings-grid">
          <label class="settings-field">
            <span>证据片段数</span>
            <input id="settings-top-k" type="number" min="1" max="8" step="1" />
          </label>
          <label class="settings-check">
            <input id="settings-strict-grounded" type="checkbox" />
            <span>严格证据模式</span>
          </label>
          <label class="settings-check">
            <input id="settings-use-rerank" type="checkbox" />
            <span>启用重排 (Rerank)</span>
          </label>
        </div>
        <div class="settings-actions">
          <button id="settings-save" class="primary-button compact-button" type="button">应用</button>
          <button id="settings-refresh-docs" class="ghost-button compact-button" type="button">刷新文档</button>
        </div>
        <div class="settings-section">
          <h3>已导入文档</h3>
          <div id="settings-documents" class="settings-documents"></div>
        </div>
      </div>
    `;
    document.body.appendChild(panel);
  }

  if (panel.dataset.bound === "true") return panel;
  panel.dataset.bound = "true";

  panel.querySelector("#settings-close").addEventListener("click", closeSettingsPanel);
  panel.addEventListener("click", (event) => {
    if (event.target === panel) closeSettingsPanel();
  });

  // Provider toggle
  const providerSelect = panel.querySelector("#settings-provider");
  providerSelect.addEventListener("change", () => syncProviderFields(panel));

  // Fetch available models
  panel.querySelector("#settings-fetch-models").addEventListener("click", async () => {
    const provider = panel.querySelector("#settings-provider").value;
    const apiKey = panel.querySelector("#settings-api-key").value.trim();
    const baseUrl = panel.querySelector("#settings-base-url").value.trim();
    const statusEl = document.getElementById("settings-model-status");
    const modelSelect = panel.querySelector("#settings-model-select");
    const modelInput = panel.querySelector("#settings-model");
    const fetchBtn = panel.querySelector("#settings-fetch-models");

    if (!apiKey) {
      if (statusEl) {
        statusEl.textContent = "请先填写 API Key";
        statusEl.className = "settings-model-status status-warn";
      }
      return;
    }

    fetchBtn.disabled = true;
    fetchBtn.textContent = "获取中...";
    try {
      const data = await listAvailableModels({ provider, api_key: apiKey, base_url: baseUrl });
      const models = data.models || [];
      if (models.length === 0) {
        if (statusEl) {
          statusEl.textContent = "未获取到可用模型";
          statusEl.className = "settings-model-status status-warn";
        }
        return;
      }
      const currentModel = getSelectedModel(panel);
      modelSelect.innerHTML = models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
      if (currentModel && models.includes(currentModel)) {
        modelSelect.value = currentModel;
      }
      modelSelect.hidden = false;
      modelInput.hidden = true;
      if (statusEl) {
        statusEl.textContent = `获取到 ${models.length} 个模型`;
        statusEl.className = "settings-model-status status-ok";
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "获取模型失败: " + (err.message || "未知错误");
        statusEl.className = "settings-model-status status-warn";
      }
    } finally {
      fetchBtn.disabled = false;
      fetchBtn.textContent = "获取模型";
    }
  });

  // Click model-select to switch back to text input
  panel.querySelector("#settings-model-select").addEventListener("dblclick", () => {
    const modelSelect = panel.querySelector("#settings-model-select");
    const modelInput = panel.querySelector("#settings-model");
    modelSelect.hidden = true;
    modelInput.hidden = false;
    modelInput.focus();
  });

  panel.querySelector("#settings-model-profiles")?.addEventListener("click", async (event) => {
    const button = event.target.closest(".settings-profile-use");
    const row = event.target.closest(".settings-profile");
    if (!button || !row) return;
    const profileId = row.dataset.profileId;
    const profile = (appSettings.modelProfiles || []).find((item) => item.id === profileId);
    if (!profile) return;

    fillModelFields(panel, profile);
    button.disabled = true;
    button.textContent = "切换中...";
    const statusEl = document.getElementById("settings-model-status");
    try {
      const result = await updateModelSettings({ profile_id: profileId });
      appSettings = saveSettings({
        ...appSettings,
        modelProvider: result.provider || profile.provider,
        modelBaseUrl: result.base_url || profile.base_url || "",
        modelName: result.model || profile.model,
        activeProfileId: result.active_profile_id || result.profile?.id || profileId,
        modelProfiles: mergeModelProfiles(appSettings.modelProfiles, result.profiles || []),
      });
      fillModelFields(panel, {
        provider: appSettings.modelProvider,
        base_url: appSettings.modelBaseUrl,
        model: appSettings.modelName,
      });
      renderModelProfiles(panel);
      if (statusEl) {
        statusEl.textContent = `已切换 · ${result.model || profile.model}`;
        statusEl.className = "settings-model-status status-ok";
      }
      showToast(`已切换到 ${result.model || profile.model}`, "success");
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "切换失败: " + (err.message || "未知错误");
        statusEl.className = "settings-model-status status-warn";
      }
      showToast("模型切换失败", "error");
    } finally {
      button.disabled = false;
      button.textContent = "切换";
    }
  });

  panel.querySelector("#settings-save").addEventListener("click", async () => {
    const topK = Number(panel.querySelector("#settings-top-k").value);
    const strictGrounded = panel.querySelector("#settings-strict-grounded").checked;
    const useRerank = panel.querySelector("#settings-use-rerank").checked;
    const profileName = panel.querySelector("#settings-profile-name")?.value.trim() || "";
    const provider = panel.querySelector("#settings-provider").value;
    const apiKey = panel.querySelector("#settings-api-key").value.trim();
    const baseUrl = panel.querySelector("#settings-base-url").value.trim();
    const model = getSelectedModel(panel);

    appSettings = saveSettings({
      topK,
      strictGrounded,
      useRerank,
      modelProvider: provider,
      modelApiKey: apiKey || appSettings.modelApiKey,
      modelBaseUrl: baseUrl,
      modelName: model,
      modelProfiles: appSettings.modelProfiles,
    });

    // If API key provided, update backend
    if (apiKey || model) {
      const statusEl = document.getElementById("settings-model-status");
      try {
        const result = await updateModelSettings({ provider, api_key: apiKey, base_url: baseUrl, model, name: profileName });
        appSettings = saveSettings({
          ...appSettings,
          modelProvider: result.provider || provider,
          modelBaseUrl: baseUrl || result.base_url || "",
          modelName: result.model || model,
          activeProfileId: result.active_profile_id || result.profile?.id || "",
          modelProfiles: mergeModelProfiles(appSettings.modelProfiles, result.profiles || []),
        });
        showModelTextInput(panel, appSettings.modelName);
        renderModelProfiles(panel);
        if (statusEl) {
          statusEl.textContent = `已连接 · ${result.model}${result.chat_enabled ? "" : " (Key 无效)"}`;
          statusEl.className = "settings-model-status " + (result.chat_enabled ? "status-ok" : "status-warn");
        }
        showToast(`模型配置已更新：${result.model}`, "success");
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = "连接失败: " + (err.message || "未知错误");
          statusEl.className = "settings-model-status status-warn";
        }
        showToast("模型配置更新失败", "error");
      }
    } else {
      showToast(`已应用：${appSettings.topK} 个证据片段`, "success");
    }

    closeSettingsPanel();
  });
  panel.querySelector("#settings-refresh-docs").addEventListener("click", refreshDocumentList);
  return panel;
}

async function openSettingsPanel() {
  const panel = ensureSettingsPanel();
  panel.querySelector("#settings-top-k").value = String(appSettings.topK);
  panel.querySelector("#settings-strict-grounded").checked = appSettings.strictGrounded;
  panel.querySelector("#settings-use-rerank").checked = appSettings.useRerank;
  panel.querySelector("#settings-profile-name").value = "";
  panel.querySelector("#settings-provider").value = appSettings.modelProvider || "dashscope";
  panel.querySelector("#settings-api-key").value = appSettings.modelApiKey || "";
  panel.querySelector("#settings-base-url").value = appSettings.modelBaseUrl || "";
  showModelTextInput(panel, appSettings.modelName || "qwen-plus");
  syncProviderFields(panel);
  renderModelProfiles(panel);

  clearTimeout(settingsCloseTimer);
  panel.classList.remove("settings-panel-closing");
  panel.hidden = false;
  panel.querySelector("#settings-top-k").focus();
  refreshDocumentList();
  closeSessionSidebarOnSmallScreen();

  // Fetch current model status from backend
  try {
    const modelStatus = await getModelSettings();
    const savedRawSettings = JSON.parse(window.localStorage.getItem("research-agent-settings") || "{}");
    appSettings = saveSettings({
      ...appSettings,
      modelProvider: savedRawSettings.modelProvider || modelStatus.provider || appSettings.modelProvider || "dashscope",
      modelBaseUrl: savedRawSettings.modelBaseUrl || modelStatus.base_url || appSettings.modelBaseUrl || "",
      modelName: savedRawSettings.modelName || modelStatus.model || appSettings.modelName || "qwen-plus",
      activeProfileId: modelStatus.active_profile_id || savedRawSettings.activeProfileId || appSettings.activeProfileId || "",
      modelProfiles: mergeModelProfiles(savedRawSettings.modelProfiles || appSettings.modelProfiles || [], modelStatus.profiles || []),
    });
    panel.querySelector("#settings-provider").value = appSettings.modelProvider || "dashscope";
    panel.querySelector("#settings-base-url").value = appSettings.modelBaseUrl || "";
    showModelTextInput(panel, appSettings.modelName || modelStatus.model || "qwen-plus");
    syncProviderFields(panel);
    renderModelProfiles(panel);
    const statusEl = document.getElementById("settings-model-status");
    if (statusEl) {
      if (modelStatus.chat_enabled) {
        statusEl.textContent = `已连接 · ${modelStatus.model}`;
        statusEl.className = "settings-model-status status-ok";
      } else if (modelStatus.api_key) {
        statusEl.textContent = "API Key 已设置（未验证）";
        statusEl.className = "settings-model-status status-warn";
      } else {
        statusEl.textContent = "未配置 API Key，使用本地规则模式";
        statusEl.className = "settings-model-status";
      }
    }
  } catch {
    // ignore fetch errors
  }
}

function closeSettingsPanel() {
  const panel = document.getElementById("settings-panel");
  if (!panel || panel.hidden || panel.classList.contains("settings-panel-closing")) return;
  panel.classList.add("settings-panel-closing");
  clearTimeout(settingsCloseTimer);
  settingsCloseTimer = setTimeout(() => {
    panel.hidden = true;
    panel.classList.remove("settings-panel-closing");
    settingsButton?.focus();
  }, 260);
}

function setComposerBusy(isBusy) {
  setIsSubmitting(isBusy);
  if (chatSubmit) {
    chatSubmit.disabled = isBusy;
    chatSubmit.classList.toggle("is-loading", isBusy);
    chatSubmit.setAttribute("aria-busy", isBusy ? "true" : "false");
  }
  if (chatStop) {
    chatStop.hidden = !isBusy;
    chatStop.disabled = !isBusy;
  }
}

async function submitQuestion(event, questionOverride) {
  event?.preventDefault?.();
  const question = (questionOverride || chatInput.value).trim();
  if (!question) return;
  if (getIsSubmitting()) return;

  setComposerBusy(true);
  clearDraft();
  chatInput.value = question;

  const payload = {
    question,
    top_k: appSettings.topK,
    session_id: getCurrentSessionId() || undefined,
    strict_grounded: appSettings.strictGrounded,
    use_rerank: appSettings.useRerank,
  };

  try {
    await runChatStream(payload, {
      onError: (message) => showToast(message, "error"),
      onAbort: () => showToast("已停止生成", "info"),
      onRetry: () => submitQuestion(null, getLastStreamQuestion() || question),
    });
  } finally {
    setComposerBusy(false);
    chatInput.value = "";
    chatInput.style.height = "auto";
    chatInput.focus();
  }
}

// ── 1. 表单提交 ──────────────────────────────────────────────
chatForm.addEventListener("submit", submitQuestion);
chatSubmit.addEventListener("click", submitQuestion);
chatStop?.addEventListener("click", () => {
  if (!getIsSubmitting()) return;
  abortChatStream();
});

// ── 2. Textarea 自动增高 ────────────────────────────────────
chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + "px";
});

// ── 3. Enter 提交 / Shift+Enter 换行 ─────────────────────────
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

// ── 4. 草稿自动保存 ─────────────────────────────────────────
let draftTimer = null;
chatInput.addEventListener("input", () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    saveDraft(chatInput.value);
  }, 300);
});

// ── 5. 新对话按钮 ───────────────────────────────────────────
newChatButton.addEventListener("click", async () => {
  toggleWelcomeScreen(true);
  for (const child of [...chatMessages.children]) {
    if (child !== welcomeScreen) child.remove();
  }
  await createSession();
  closeSessionSidebarOnSmallScreen();
  chatInput.focus();
});

// ── 6. 清空对话按钮 ─────────────────────────────────────────
clearChatButton.addEventListener("click", async () => {
  const sessionToDelete = getCurrentSessionId();
  if (sessionToDelete) {
    const confirmed = await confirmAction({
      title: "清空当前对话？",
      message: "历史消息会一起清空。",
      confirmText: "清空",
      tone: "danger",
    });
    if (!confirmed) return;
  }
  // 先清空 UI
  toggleWelcomeScreen(true);
  for (const child of [...chatMessages.children]) {
    if (child !== welcomeScreen) child.remove();
  }
  chatInput.focus();
  // 再异步清理后端（不阻塞 UI）
  if (sessionToDelete) {
    try { await deleteSession(sessionToDelete); } catch { /* ignore */ }
  }
});

// ── 上传文档 ─────────────────────────────────────────────────
const uploadDocButton = document.getElementById("upload-doc-button");
const uploadFileInput = document.getElementById("upload-file-input");

if (uploadDocButton && uploadFileInput) {
  uploadDocButton.addEventListener("click", () => {
    uploadFileInput.click();
    closeSessionSidebarOnSmallScreen();
  });

  uploadFileInput.addEventListener("change", async () => {
    const file = uploadFileInput.files[0];
    if (!file) return;

    const validTypes = [".pdf", ".docx", ".txt"];
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!validTypes.includes(ext)) {
      showToast("仅支持 PDF、DOCX、TXT 格式", "error");
      uploadFileInput.value = "";
      return;
    }

    uploadDocButton.disabled = true;
    uploadDocButton.textContent = "导入中...";
    try {
      const result = await uploadDocument(file);
      const count = Array.isArray(result.documents) ? result.documents.length : result.imported_count;
      showToast(`已导入：${result.filename || result.title || file.name}${count ? ` · 共 ${count} 篇` : ""}`, "success");
      uploadFileInput.value = "";
      refreshDocumentList();
      refreshWorkspaceDocuments();
    } catch (err) {
      showToast("导入失败：" + (err.message || "未知错误"), "error");
    } finally {
      uploadDocButton.disabled = false;
      uploadDocButton.textContent = "";
      const iconSpan = document.createElement("span");
      iconSpan.setAttribute("aria-hidden", "true");
      iconSpan.textContent = "\u{1F4C4}";
      uploadDocButton.appendChild(iconSpan);
      uploadDocButton.appendChild(document.createTextNode(" 导入文档"));
    }
  });
}

if (settingsButton) {
  settingsButton.addEventListener("click", openSettingsPanel);
}

initWorkspace();

// ── 7. 侧栏切换 ─────────────────────────────────────────────
sidebarToggle.addEventListener("click", () => {
  const nextIsOpen = appShell.classList.contains("sidebar-collapsed");
  setSessionSidebarOpen(nextIsOpen);
});

// ── 8. 会话列表点击委托 ─────────────────────────────────────
sessionsOutput.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.classList.contains("session-open")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    toggleWelcomeScreen(false);
    for (const child of [...chatMessages.children]) {
      if (child !== welcomeScreen) child.remove();
    }
    const data = await loadSession(sessionId);
    renderSessionHistory(data.messages);
    scrollToBottom({ smooth: false });
    closeSessionSidebarOnSmallScreen();
    return;
  }

  if (button.classList.contains("delete-session")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    const confirmed = await confirmAction({
      title: "删除该会话？",
      message: "删除后会从历史列表移除。",
      confirmText: "删除",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await deleteSession(sessionId);
      if (sessionId === getCurrentSessionId()) {
        toggleWelcomeScreen(true);
        for (const child of [...chatMessages.children]) {
          if (child !== welcomeScreen) child.remove();
        }
      }
    } catch (err) {
      console.warn("删除会话失败:", err);
    }
    return;
  }
});

// ── 9. 键盘快捷键 ───────────────────────────────────────────
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const panel = document.getElementById("settings-panel");
    if (panel && !panel.hidden) {
      closeSettingsPanel();
      return;
    }
    if (compactSessionSidebarQuery.matches && appShell.classList.contains("sidebar-collapsed") === false) {
      setSessionSidebarOpen(false);
    }
    return;
  }

  if (!event.altKey) return;
  const tag = document.activeElement?.tagName;
  if (tag === "TEXTAREA" || (tag === "INPUT" && document.activeElement.type !== "checkbox")) {
    return;
  }

  if (event.key === "n" || event.key === "N") {
    event.preventDefault();
    newChatButton.click();
    return;
  }
  if (event.key === "s" || event.key === "S") {
    event.preventDefault();
    sidebarToggle.click();
    return;
  }
});

// ── 10. 移动端左滑关闭侧栏手势 ──────────────────────────────
const SWIPE_THRESHOLD = 80;

function addSwipeListener(el, direction, callback) {
  if (!el) return;
  let startX = 0;
  let startY = 0;
  let tracking = false;

  el.addEventListener("touchstart", (e) => {
    const touch = e.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    tracking = true;
  }, { passive: true });

  el.addEventListener("touchmove", (e) => {
    if (!tracking) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    if (Math.abs(dy) > Math.abs(dx)) {
      tracking = false;
    }
  }, { passive: true });

  el.addEventListener("touchend", (e) => {
    if (!tracking) return;
    tracking = false;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - startX;
    if (direction === "right" && dx > SWIPE_THRESHOLD) {
      callback();
    }
    if (direction === "left" && dx < -SWIPE_THRESHOLD) {
      callback();
    }
  }, { passive: true });
}

addSwipeListener(sidebar, "left", () => {
  if (compactSessionSidebarQuery.matches) {
    setSessionSidebarOpen(false);
  }
});

// ── 11. 响应式 media query 监听 ─────────────────────────────
if (compactSessionSidebarQuery.addEventListener) {
  compactSessionSidebarQuery.addEventListener("change", () => {
    if (getStoredSessionSidebarState() === null) {
      setSessionSidebarOpen(!compactSessionSidebarQuery.matches, { persist: false });
    }
  });
}

// ── 欢迎屏快捷提问 ───────────────────────────────────────────
document.querySelectorAll(".welcome-prompt").forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = button.dataset.prompt || "";
    if (!prompt || getIsSubmitting()) return;
    chatInput.value = prompt;
    chatForm.requestSubmit();
  });
});

// ── 12. 初始化 ──────────────────────────────────────────────
setSessionSidebarOpen(shouldStartWithSessionSidebarOpen(), { persist: false });
const draft = loadDraft();
if (draft) {
  chatInput.value = draft;
}
toggleWelcomeScreen(true);
refreshSessions();
renderLatestEvidence();
refreshWorkspaceStatus();

window.__DODO_CHAT_READY = true;
