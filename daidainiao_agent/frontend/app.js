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

import { refreshSessions, loadSession, createSession, deleteSession, uploadDocument, getModelSettings, updateModelSettings, listAvailableModels, truncateSession } from "./api.js";
import { runChatStream, abortChatStream, getLastStreamQuestion } from "./stream.js";
import { initWorkspace, openWorkspace, closeWorkspace, openWorkspaceTab, renderLatestEvidence, refreshWorkspaceDocuments, refreshWorkspaceStatus, runWorkspaceLabFromCases } from "./workspace.js";
import {
  toggleWelcomeScreen, scrollToBottom, renderSessionHistory, bindUserMessageActions,
} from "./render/chat.js";
import { escapeHtml } from "./render/escape.js";

import {
  shouldStartWithSessionSidebarOpen, setSessionSidebarOpen,
  getStoredSessionSidebarState, closeSessionSidebarOnSmallScreen,
} from "./handlers/sidebar.js";
import { confirmAction } from "./confirm.js";
import { setSessionSearchQuery } from "./render/sessions.js";
import { loadDemoSession } from "./demo.js";
import { applyQualityPreset, getEffectiveAskOptions } from "./quality-preset.js";
import { trackEvent } from "./analytics.js";
import {
  bindSettingsFocusTrap,
  clearShellInert,
  dismissSettingsPanelAnimated,
  focusSettingsButton,
  focusSettingsCloseButton,
  removeSettingsFocusTrap,
  setSettingsShellInert,
  setModalBackdropInert,
} from "./overlay.js";

const densityQuery = window.matchMedia("(max-width: 768px)");
const pointerFineQuery = window.matchMedia("(any-pointer: fine)");

function syncViewportDensityMode() {
  if (!document.documentElement?.classList?.toggle) return;
  const isHighScaleNarrowDesktop =
    densityQuery.matches &&
    pointerFineQuery.matches &&
    window.devicePixelRatio > 2;
  document.documentElement.classList.toggle("narrow-desktop-density", isHighScaleNarrowDesktop);
}

syncViewportDensityMode();
if (typeof window.addEventListener === "function") {
  window.addEventListener("resize", syncViewportDensityMode);
}
if (densityQuery.addEventListener) {
  densityQuery.addEventListener("change", syncViewportDensityMode);
}
if (pointerFineQuery.addEventListener) {
  pointerFineQuery.addEventListener("change", syncViewportDensityMode);
}

function bindGlobalUiRouter() {
  if (window.__DODO_UI_ROUTER_BOUND) return;
  window.__DODO_UI_ROUTER_BOUND = true;

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const button = target.closest("button");
    const welcomePrompt = target.closest(".welcome-prompt");
    const presetBtn = target.closest(".quality-preset-btn");

    if (button) {
      switch (button.id) {
        case "settings-button":
          event.preventDefault();
          void openSettingsPanel();
          return;
        case "settings-manage-knowledge":
          event.preventDefault();
          openKnowledgeFromSettings();
          return;
        case "new-chat":
          event.preventDefault();
          void handleNewChat();
          return;
        case "clear-chat":
          event.preventDefault();
          void handleClearChat();
          return;
        case "upload-doc-button": {
          event.preventDefault();
          const input = document.getElementById("upload-file-input");
          input?.click();
          closeSessionSidebarOnSmallScreen();
          return;
        }
        case "workspace-toggle":
          event.preventDefault();
          openWorkspace();
          closeSessionSidebarOnSmallScreen();
          return;
        case "workspace-close":
          event.preventDefault();
          closeWorkspace();
          return;
        case "load-demo-session":
          event.preventDefault();
          void loadDemoSession()
            .then(() => {
              renderLatestEvidence();
              scrollToBottom({ smooth: true });
            })
            .catch((error) => showToast(error.message || "加载示例失败", "error"));
          return;
        case "chat-submit":
          event.preventDefault();
          void submitQuestion(event);
          return;
        case "chat-stop":
          event.preventDefault();
          if (getIsSubmitting()) abortChatStream();
          return;
        case "sidebar-toggle":
          event.preventDefault();
          if (appShell?.classList) {
            const isOpen = appShell.classList.contains("sidebar-open")
              && !appShell.classList.contains("sidebar-collapsed");
            setSessionSidebarOpen(!isOpen);
          }
          return;
        default:
          break;
      }
    }

    const statusCapsule = target.closest("#header-status-capsule");
    if (statusCapsule) {
      event.preventDefault();
      openWorkspaceTab("status");
      closeSessionSidebarOnSmallScreen();
      return;
    }

    if (welcomePrompt && chatInput) {
      event.preventDefault();
      const text = welcomePrompt.dataset.prompt || welcomePrompt.textContent || "";
      chatInput.value = text.trim();
      chatInput.focus();
      chatInput.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    if (presetBtn) {
      event.preventDefault();
      const preset = presetBtn.dataset.preset === "fast" ? "fast" : "accurate";
      appSettings = applyQualityPreset(appSettings, preset);
      syncQualityPresetButtons();
      updateHeaderStatusCapsule();
      trackEvent("quality_preset_change", { preset });
    }
  }, true);

  window.__DODO_UI_BOUND = true;
}

bindGlobalUiRouter();

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "dark" || theme === "light") {
    root.setAttribute("data-theme", theme);
  } else {
    root.removeAttribute("data-theme");
  }
}

if (chatForm) {
  chatForm.setAttribute("action", "javascript:void(0)");
}

let appSettings = loadSettings();

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

function getActiveProfile() {
  const id = activeProfileId();
  if (!id) return null;
  return (appSettings.modelProfiles || []).find((item) => item.id === id) || null;
}

function fillProfileNameField(panel) {
  const input = panel.querySelector("#settings-profile-name");
  if (!input) return;
  const active = getActiveProfile();
  input.value = active?.name || "";
  input.placeholder = active ? "当前配置名称（可选修改）" : "新建配置时填写名称";
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
  const modelRow = panel.querySelector(".settings-model-row");
  if (modelSelect) {
    modelSelect.hidden = true;
  }
  if (modelInput) {
    modelInput.hidden = false;
    if (value) {
      modelInput.value = value;
    }
  }
  modelRow?.classList.remove("is-picker");
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

const IMPORT_SUCCESS_DURATION_MS = 5000;

function dismissImportSuccessNotice() {
  const overlay = document.getElementById("import-success-overlay");
  if (!overlay) return;
  clearTimeout(dismissImportSuccessNotice.autoTimer);
  clearTimeout(dismissImportSuccessNotice.removeTimer);
  if (dismissImportSuccessNotice.onKeydown) {
    document.removeEventListener("keydown", dismissImportSuccessNotice.onKeydown);
    dismissImportSuccessNotice.onKeydown = null;
  }
  setModalBackdropInert(false);
  overlay.classList.remove("import-success-overlay-visible");
  dismissImportSuccessNotice.removeTimer = setTimeout(() => {
    overlay.remove();
    document.getElementById("upload-doc-button")?.focus();
  }, 220);
}

function showImportSuccessNotice({ title, subtitle = "", warning = "" }) {
  const existing = document.getElementById("import-success-overlay");
  if (existing) {
    clearTimeout(dismissImportSuccessNotice.autoTimer);
    clearTimeout(dismissImportSuccessNotice.removeTimer);
    existing.remove();
  }

  const overlay = document.createElement("div");
  overlay.id = "import-success-overlay";
  overlay.className = "import-success-overlay";
  overlay.setAttribute("role", "alertdialog");
  overlay.setAttribute("aria-live", "polite");
  overlay.setAttribute("aria-label", "导入成功");

  const warningHtml = warning
    ? `<p class="import-success-warning">${escapeHtml(warning)}</p>`
    : "";

  overlay.innerHTML = `
    <div class="import-success-card">
      <div class="import-success-icon" aria-hidden="true">
        <img src="/static/icons/dodo-official.png" width="56" height="56" alt="" />
      </div>
      <p class="import-success-kicker">导入成功</p>
      <h3 class="import-success-title">${escapeHtml(title)}</h3>
      ${subtitle ? `<p class="import-success-subtitle">${escapeHtml(subtitle)}</p>` : ""}
      ${warningHtml}
      <div class="import-success-progress" aria-hidden="true"><span></span></div>
      <p class="import-success-hint">点击任意处关闭 · 5 秒后自动消失</p>
    </div>
  `;

  overlay.addEventListener("click", dismissImportSuccessNotice);
  document.body.appendChild(overlay);
  setModalBackdropInert(true);
  dismissImportSuccessNotice.onKeydown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dismissImportSuccessNotice();
    }
  };
  document.addEventListener("keydown", dismissImportSuccessNotice.onKeydown);
  requestAnimationFrame(() => overlay.classList.add("import-success-overlay-visible"));
  dismissImportSuccessNotice.autoTimer = setTimeout(dismissImportSuccessNotice, IMPORT_SUCCESS_DURATION_MS);
}

function openKnowledgeFromSettings() {
  dismissSettingsPanelAnimated(() => {
    openWorkspaceTab("documents");
    closeSessionSidebarOnSmallScreen();
  });
}

function ensureSettingsPanel() {
  const panel = document.getElementById("settings-panel");
  if (!panel) {
    console.error("呆呆鸟：缺少 #settings-panel，请检查 index.html");
    return null;
  }
  bindSettingsPanelEvents(panel);
  return panel;
}

function settingField(panel, selector) {
  return panel?.querySelector(selector) || null;
}

function bindSettingsPanelEvents(panel) {
  if (!panel || panel.dataset.bound === "true") return;
  panel.dataset.bound = "true";

  const closeBtn = settingField(panel, "#settings-close");
  if (!closeBtn) {
    console.error("呆呆鸟：设置面板缺少 #settings-close");
    return;
  }
  closeBtn.addEventListener("click", closeSettingsPanel);
  panel.addEventListener("click", (event) => {
    if (event.target === panel) closeSettingsPanel();
  });

  const providerSelect = settingField(panel, "#settings-provider");
  providerSelect?.addEventListener("change", () => syncProviderFields(panel));

  settingField(panel, "#settings-fetch-models")?.addEventListener("click", async () => {
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
      panel.querySelector(".settings-model-row")?.classList.add("is-picker");
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
  settingField(panel, "#settings-model-select")?.addEventListener("dblclick", () => {
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
      fillProfileNameField(panel);
      updateHeaderStatusCapsule();
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

  panel.querySelector("#settings-save")?.addEventListener("click", async () => {
    const topK = Number(panel.querySelector("#settings-top-k").value);
    const strictGrounded = panel.querySelector("#settings-strict-grounded").checked;
    const useRerank = panel.querySelector("#settings-use-rerank").checked;
    const selfCorrect = panel.querySelector("#settings-self-correct").checked;
    const autoSyncEvidence = panel.querySelector("#settings-auto-sync-evidence").checked;
    const theme = panel.querySelector("#settings-theme").value;
    const profileName = panel.querySelector("#settings-profile-name")?.value.trim() || "";
    const provider = panel.querySelector("#settings-provider").value;
    const apiKey = panel.querySelector("#settings-api-key").value.trim();
    const baseUrl = panel.querySelector("#settings-base-url").value.trim();
    const model = getSelectedModel(panel);
    const statusEl = document.getElementById("settings-model-status");
    const activeId = activeProfileId();
    const activeProfile = getActiveProfile();
    const hasNewApiKey = Boolean(apiKey);
    const modelChanged = Boolean(
      model &&
        model !== (activeProfile?.model || appSettings.modelName || ""),
    );
    const providerChanged = provider !== (activeProfile?.provider || appSettings.modelProvider || "dashscope");
    const baseUrlChanged = baseUrl !== (activeProfile?.base_url || appSettings.modelBaseUrl || "");
    const modelFieldsChanged = hasNewApiKey || modelChanged || providerChanged || baseUrlChanged;
    const creatingNewProfile = modelFieldsChanged && !activeId;

    if (creatingNewProfile && !profileName) {
      if (statusEl) {
        statusEl.textContent = "新建配置请填写配置名称";
        statusEl.className = "settings-model-status status-warn";
      }
      showToast("新建配置请填写配置名称", "error");
      panel.querySelector("#settings-profile-name")?.focus();
      return;
    }

    appSettings = saveSettings({
      topK,
      strictGrounded,
      useRerank,
      selfCorrect,
      autoSyncEvidence,
      theme,
      modelProvider: provider,
      modelApiKey: apiKey || appSettings.modelApiKey,
      modelBaseUrl: baseUrl,
      modelName: model,
      modelProfiles: appSettings.modelProfiles,
    });

    if (modelFieldsChanged) {
      try {
        const payload = { provider, base_url: baseUrl, model };
        if (apiKey) payload.api_key = apiKey;
        if (activeId) {
          payload.profile_id = activeId;
          if (profileName) payload.name = profileName;
        } else if (profileName) {
          payload.name = profileName;
        }
        const result = await updateModelSettings(payload);
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
        showToast(`已保存并应用：${profileName || result.model}`, "success");
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

    applyTheme(appSettings.theme);
    updateHeaderStatusCapsule();
    syncQualityPresetButtons();
    closeSettingsPanel();
  });
  panel.querySelector("#settings-manage-knowledge")?.addEventListener("click", openKnowledgeFromSettings);
}

async function openSettingsPanel() {
  try {
    closeWorkspace();
    const panel = ensureSettingsPanel();
    if (!panel) {
      showToast("设置面板加载失败", "error");
      return;
    }
    const topK = settingField(panel, "#settings-top-k");
    if (topK) topK.value = String(appSettings.topK);
    const strictGrounded = settingField(panel, "#settings-strict-grounded");
    if (strictGrounded) strictGrounded.checked = appSettings.strictGrounded;
    const useRerank = settingField(panel, "#settings-use-rerank");
    if (useRerank) useRerank.checked = appSettings.useRerank;
    const selfCorrect = settingField(panel, "#settings-self-correct");
    if (selfCorrect) selfCorrect.checked = appSettings.selfCorrect !== false;
    const autoSync = settingField(panel, "#settings-auto-sync-evidence");
    if (autoSync) autoSync.checked = appSettings.autoSyncEvidence !== false;
    const theme = settingField(panel, "#settings-theme");
    if (theme) theme.value = appSettings.theme || "system";
    const provider = settingField(panel, "#settings-provider");
    if (provider) provider.value = appSettings.modelProvider || "dashscope";
    const apiKey = settingField(panel, "#settings-api-key");
    if (apiKey) apiKey.value = appSettings.modelApiKey || "";
    const baseUrl = settingField(panel, "#settings-base-url");
    if (baseUrl) baseUrl.value = appSettings.modelBaseUrl || "";
    showModelTextInput(panel, appSettings.modelName || "qwen-plus");
    syncProviderFields(panel);
    renderModelProfiles(panel);
    fillProfileNameField(panel);

    panel.classList.remove("settings-panel-closing");
    panel.hidden = false;
    setSettingsShellInert(true);
    bindSettingsFocusTrap(panel);
    focusSettingsCloseButton();
    closeSessionSidebarOnSmallScreen();

  // Fetch current model status from backend
  try {
    const modelStatus = await getModelSettings();
    const savedRawSettings = JSON.parse(window.localStorage.getItem("daidainiao-agent-settings") || "{}");
    appSettings = saveSettings({
      ...appSettings,
      modelProvider: savedRawSettings.modelProvider || modelStatus.provider || appSettings.modelProvider || "dashscope",
      modelBaseUrl: savedRawSettings.modelBaseUrl || modelStatus.base_url || appSettings.modelBaseUrl || "",
      modelName: savedRawSettings.modelName || modelStatus.model || appSettings.modelName || "qwen-plus",
      modelApiKey: savedRawSettings.modelApiKey || modelStatus.api_key || appSettings.modelApiKey || "",
      activeProfileId: modelStatus.active_profile_id || savedRawSettings.activeProfileId || appSettings.activeProfileId || "",
      modelProfiles: mergeModelProfiles(savedRawSettings.modelProfiles || appSettings.modelProfiles || [], modelStatus.profiles || []),
    });
    panel.querySelector("#settings-provider").value = appSettings.modelProvider || "dashscope";
    panel.querySelector("#settings-api-key").value = appSettings.modelApiKey || "";
    panel.querySelector("#settings-base-url").value = appSettings.modelBaseUrl || "";
    showModelTextInput(panel, appSettings.modelName || modelStatus.model || "qwen-plus");
    syncProviderFields(panel);
    renderModelProfiles(panel);
    fillProfileNameField(panel);
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
    updateHeaderStatusCapsule();
  } catch {
    // ignore fetch errors
  }
  } catch (error) {
    console.error("打开设置失败:", error);
    showToast("设置面板打开失败，请刷新页面重试", "error");
    const failedPanel = document.getElementById("settings-panel");
    if (failedPanel) {
      failedPanel.hidden = true;
      failedPanel.classList.remove("settings-panel-closing");
    }
    setSettingsShellInert(false);
    removeSettingsFocusTrap();
  }
}

function closeSettingsPanel() {
  const panel = document.getElementById("settings-panel");
  if (!panel || panel.hidden || panel.classList.contains("settings-panel-closing")) return;
  dismissSettingsPanelAnimated(() => {
    focusSettingsButton();
  });
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
  if (chatInput) {
    chatInput.readOnly = isBusy;
    chatInput.setAttribute("aria-busy", isBusy ? "true" : "false");
  }
  chatForm?.classList.toggle("is-busy", isBusy);
}

function resetUploadDocButton() {
  const button = document.getElementById("upload-doc-button");
  if (!button) return;
  button.disabled = false;
  button.innerHTML = `
    <span class="nav-icon" aria-hidden="true"><svg><use href="#icon-doc"/></svg></span>
    导入文档
  `;
}

function showChatSkeleton() {
  if (!chatMessages || !welcomeScreen) return null;
  toggleWelcomeScreen(false);
  for (const child of [...chatMessages.children]) {
    if (child !== welcomeScreen) child.remove();
  }
  const skeleton = document.createElement("div");
  skeleton.className = "chat-skeleton";
  skeleton.innerHTML = `
    <div class="chat-skeleton-line chat-skeleton-line-wide"></div>
    <div class="chat-skeleton-line chat-skeleton-line-medium"></div>
    <div class="chat-skeleton-line chat-skeleton-line-short"></div>
  `;
  chatMessages.appendChild(skeleton);
  return skeleton;
}

function updateChatHeaderTitle(title) {
  const heading = document.getElementById("assistant-title");
  if (!heading) return;
  const normalized = (title || "").trim();
  if (normalized && normalized !== "新会话") {
    heading.textContent = normalized;
    heading.title = normalized;
  } else {
    heading.textContent = "呆呆鸟";
    heading.title = "呆呆鸟";
  }
}

async function submitQuestion(event, questionOverride) {
  event?.preventDefault?.();
  const question = (questionOverride || chatInput.value).trim();
  if (!question) {
    showToast("请输入问题", "info");
    chatForm?.classList.add("composer-shake");
    setTimeout(() => chatForm?.classList.remove("composer-shake"), 180);
    return;
  }
  if (getIsSubmitting()) return;

  setComposerBusy(true);
  clearDraft();
  chatInput.value = "";
  chatInput.style.height = "auto";

  const payload = {
    question,
    session_id: getCurrentSessionId() || undefined,
    ...getEffectiveAskOptions(appSettings),
  };

  try {
    await runChatStream(payload, {
      onError: (message) => showToast(message, "error"),
      onAbort: () => showToast("已停止生成", "info"),
      onRetry: () => submitQuestion(null, getLastStreamQuestion() || question),
    });
  } finally {
    setComposerBusy(false);
    chatInput.focus();
  }
}

async function handleNewChat() {
  toggleWelcomeScreen(true);
  if (chatMessages) {
    for (const child of [...chatMessages.children]) {
      if (child !== welcomeScreen) child.remove();
    }
  }
  await createSession();
  updateChatHeaderTitle("呆呆鸟");
  closeSessionSidebarOnSmallScreen();
  chatInput?.focus();
}

async function handleClearChat() {
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
  toggleWelcomeScreen(true);
  if (chatMessages) {
    for (const child of [...chatMessages.children]) {
      if (child !== welcomeScreen) child.remove();
    }
  }
  chatInput?.focus();
  updateChatHeaderTitle("呆呆鸟");
  if (sessionToDelete) {
    try { await deleteSession(sessionToDelete); } catch { /* ignore */ }
  }
}

// ── 1. 表单提交 ──────────────────────────────────────────────
if (chatForm && chatInput && chatSubmit) {
  chatForm.addEventListener("submit", submitQuestion);
  window.__DODO_CHAT_READY = true;
} else {
  console.error("呆呆鸟：缺少聊天表单 DOM，主界面无法初始化。");
}

// ── 2. Textarea 自动增高 ────────────────────────────────────
chatInput?.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + "px";
});

// ── 3. Enter 提交 / Shift+Enter 换行 ─────────────────────────
chatInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm?.requestSubmit();
  }
});

// ── 4. 草稿自动保存 ─────────────────────────────────────────
let draftTimer = null;
chatInput?.addEventListener("input", () => {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    saveDraft(chatInput.value);
  }, 300);
});

// ── 上传文档 ─────────────────────────────────────────────────
const uploadDocButton = document.getElementById("upload-doc-button");
const uploadFileInput = document.getElementById("upload-file-input");

if (uploadFileInput) {
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
      const doc = result.document || {};
      const count = Array.isArray(result.documents) ? result.documents.length : doc.imported_count;
      const title = doc.title || doc.file_name || file.name;
      const subtitle = count ? `知识库共 ${count} 篇文档` : (result.message || "已加入知识库");
      showImportSuccessNotice({
        title,
        subtitle,
        warning: doc.vector_warning || "",
      });
      uploadFileInput.value = "";
      refreshWorkspaceDocuments();
    } catch (err) {
      showToast("导入失败：" + (err.message || "未知错误"), "error");
    } finally {
      resetUploadDocButton();
    }
  });
}

// ── 7. 会话列表点击委托 ─────────────────────────────────────
sessionsOutput?.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.classList.contains("session-open")) {
    const sessionId = button.dataset.sessionId;
    if (!sessionId) return;
    const skeleton = showChatSkeleton();
    try {
      const data = await loadSession(sessionId);
      skeleton?.remove();
      renderSessionHistory(data.messages);
      updateChatHeaderTitle(button.querySelector("strong")?.textContent?.trim() || "呆呆鸟");
      scrollToBottom({ smooth: false });
      closeSessionSidebarOnSmallScreen();
    } catch (err) {
      skeleton?.remove();
      toggleWelcomeScreen(true);
      showToast("加载会话失败", "error");
      console.warn("加载会话失败:", err);
    }
    return;
  }

  if (button.id === "sessions-retry") {
    event.preventDefault();
    void refreshSessions();
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
        updateChatHeaderTitle("呆呆鸟");
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
    const importOverlay = document.getElementById("import-success-overlay");
    if (importOverlay) {
      dismissImportSuccessNotice();
      return;
    }
    const panel = document.getElementById("settings-panel");
    if (panel && !panel.hidden) {
      closeSettingsPanel();
      return;
    }
    const workspacePanel = document.getElementById("workspace-panel");
    if (workspacePanel?.classList.contains("workspace-open")) {
      closeWorkspace();
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

function updateHeaderStatusCapsule() {
  const capsule = document.getElementById("header-status-capsule");
  if (!capsule) return;
  const profile = getActiveProfile();
  const preset = appSettings.qualityPreset === "fast" ? "快" : "准";
  const modelLabel = profile?.model ? profile.model : "本地规则";
  const rerank = appSettings.useRerank !== false ? "重排开" : "重排关";
  const strict = appSettings.strictGrounded !== false ? "严格证据" : "宽松";
  capsule.textContent = `${preset} · ${modelLabel} · Top ${appSettings.topK || 5}`;
  capsule.title = `点击查看运行状态 · ${preset}模式 · ${modelLabel} · Top ${appSettings.topK || 5} · ${rerank} · ${strict}`;
  capsule.classList.toggle("is-live", Boolean(profile?.model));
}

function syncQualityPresetButtons() {
  const preset = appSettings.qualityPreset === "fast" ? "fast" : "accurate";
  document.querySelectorAll(".quality-preset-btn").forEach((button) => {
    const isActive = button.dataset.preset === preset;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function shortenWelcomeLabel(text, max = 22) {
  const value = String(text || "").trim();
  if (!value) return "示例问题";
  if (/^(main|untitled|document|doc)$/i.test(value)) return "导入文档要点";
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

async function refreshWelcomePromptsFromCorpus() {
  const container = document.getElementById("welcome-prompts");
  if (!container) return;
  try {
    const { listKnowledgeDocuments } = await import("./api.js");
    const docs = await listKnowledgeDocuments({ includeBase: true });
    const items = docs.items || [];
    const imported = items.filter((item) => item.imported);
    const baseSamples = items.filter((item) => !item.imported).slice(0, 1);
    const prompts = [];
    imported.slice(0, 2).forEach((doc) => {
      const title = doc.title || doc.paper_id;
      prompts.push({
        label: `解读 ${shortenWelcomeLabel(title, 18)}`,
        question: `${title} 的核心方法、主要发现和局限是什么？`,
      });
    });
    baseSamples.forEach((doc) => {
      prompts.push({
        label: doc.paper_id === "react" ? "ReAct 与工具调用" : shortenWelcomeLabel(doc.title || doc.paper_id),
        question: doc.paper_id === "react"
          ? "ReAct 是如何结合推理与工具调用的？"
          : `简述 ${doc.title || doc.paper_id} 的主要贡献。`,
      });
    });
    if (!prompts.length) return;
    while (prompts.length < 3) {
      prompts.push({
        label: "Self-RAG 机制",
        question: "Self-RAG 的自我反思检索机制是什么？",
      });
    }
    container.innerHTML = prompts.slice(0, 3).map((item) => `
      <button type="button" class="welcome-prompt" data-prompt="${escapeHtml(item.question)}">${escapeHtml(item.label)}</button>
    `).join("");
  } catch {
    // keep static prompts
  }
}

function initLabEvalWizard() {
  el("workspace-eval-wizard-run")?.addEventListener("click", async () => {
    const raw = document.getElementById("workspace-eval-wizard-input")?.value || "";
    const cases = parseEvalWizardText(raw);
    if (!cases.length) {
      showToast("请按格式填写至少一条 eval", "error");
      return;
    }
    await runWorkspaceLabFromCases(cases);
    trackEvent("eval_wizard_run", { num_cases: cases.length });
  });

  document.getElementById("workspace-lab-eval-file")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const cases = Array.isArray(parsed) ? parsed : parsed.cases;
      if (!Array.isArray(cases) || !cases.length) {
        throw new Error("JSON 需为数组或含 cases 字段");
      }
      await runWorkspaceLabFromCases(cases);
      trackEvent("eval_file_upload", { num_cases: cases.length });
    } catch (error) {
      showToast(error.message || "Eval JSON 无效", "error");
    } finally {
      event.target.value = "";
    }
  });
}

function parseEvalWizardText(raw) {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split("|").map((part) => part.trim());
      const question = parts[0] || "";
      const expected_paper_id = parts[1] || "";
      const keywords = (parts[2] || "").split(",").map((k) => k.trim()).filter(Boolean);
      return {
        case_id: `wizard-${index + 1}`,
        question,
        expected_paper_ids: expected_paper_id ? [expected_paper_id] : [],
        expected_keywords: keywords,
      };
    })
    .filter((item) => item.question);
}

function el(id) {
  return document.getElementById(id);
}

function initSidebarScrim() {
  const scrim = document.getElementById("sidebar-scrim");
  if (!scrim || !appShell?.classList) return;
  scrim.addEventListener("click", () => {
    if (compactSessionSidebarQuery.matches) {
      setSessionSidebarOpen(false);
    }
  });
  const syncScrim = () => {
    if (!appShell?.classList) return;
    const open = appShell.classList.contains("sidebar-open")
      && !appShell.classList.contains("sidebar-collapsed");
    scrim.hidden = !compactSessionSidebarQuery.matches || !open;
    scrim.setAttribute("aria-hidden", String(scrim.hidden));
  };
  syncScrim();
  if (compactSessionSidebarQuery.addEventListener) {
    compactSessionSidebarQuery.addEventListener("change", syncScrim);
  }
  const observer = new MutationObserver(syncScrim);
  observer.observe(appShell, { attributes: true, attributeFilter: ["class"] });
}

// ── 12. 初始化 ──────────────────────────────────────────────
function bootstrapApp() {
  try {
    clearShellInert();
    ensureSettingsPanel();
    initWorkspace();
    initSidebarScrim();
    initLabEvalWizard();
    setSessionSidebarOpen(shouldStartWithSessionSidebarOpen(), { persist: false });
    const draft = loadDraft();
    if (draft && chatInput) {
      chatInput.value = draft;
    }
    toggleWelcomeScreen(true);
    applyTheme(appSettings.theme || "system");
    updateHeaderStatusCapsule();
    syncQualityPresetButtons();
    refreshWelcomePromptsFromCorpus();
    refreshSessions();
    renderLatestEvidence();
    refreshWorkspaceStatus();

    const sessionSearchInput = document.getElementById("session-search");
    if (sessionSearchInput) {
      sessionSearchInput.addEventListener("input", () => {
        setSessionSearchQuery(sessionSearchInput.value);
      });
    }

    bindUserMessageActions(async (text, userMsgIndex, isEdit) => {
      const sessionId = getCurrentSessionId();
      if (getIsSubmitting()) return;

      const userMsgs = Array.from(chatMessages.querySelectorAll(".chat-msg-user"));
      const targetUserMsg = userMsgs[userMsgIndex];
      if (!targetUserMsg) return;

      try {
        if (sessionId) {
          const truncateIndex = 2 * userMsgIndex;
          await truncateSession(sessionId, truncateIndex);
        }

        let el = targetUserMsg;
        while (el) {
          const next = el.nextElementSibling;
          el.remove();
          el = next;
        }

        await submitQuestion(null, text);
      } catch (err) {
        showToast("操作失败：" + (err.message || "未知错误"), "error");
      }
    });
  } catch (error) {
    console.error("呆呆鸟：界面初始化失败", error);
    showToast("部分功能加载失败，请硬刷新页面 (Ctrl+F5)", "error");
  }
}

bootstrapApp();
