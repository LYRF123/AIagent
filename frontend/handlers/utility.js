import {
  utilityTitle,
  utilityNavButtons,
  utilityPanels,
  utilityDrawer,
  openToolsButton,
  utilityLabels,
  getCurrentUtility,
  setCurrentUtility,
} from "../state.js";
import { fetchUsage } from "../api.js";

export function showUtilityPanel(target) {
  setCurrentUtility(target);
  utilityTitle.textContent = utilityLabels[target] || "\u5DE5\u5177\u9762\u677F";
  utilityNavButtons.forEach((button) => {
    const isActive = button.dataset.utilityPanelTarget === target;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
  utilityPanels.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.utilityPanel !== target);
  });

  if (target === "usage") {
    const output = document.getElementById("usage-output");
    if (output) {
      output.innerHTML = `<p class="empty-note">正在加载用量数据...</p>`;
      fetchUsage().then((data) => {
        output.innerHTML = renderUsagePanel(data);
      }).catch(() => {
        output.innerHTML = `<p class="empty-note">用量数据加载失败。</p>`;
      });
    }
  }
}

export function openUtilityDrawer(target = getCurrentUtility() || "presets") {
  utilityDrawer.classList.remove("hidden");
  utilityDrawer.setAttribute("aria-hidden", "false");
  if (openToolsButton) {
    openToolsButton.classList.add("active");
    openToolsButton.setAttribute("aria-expanded", "true");
  }
  showUtilityPanel(target);
}

function renderUsagePanel(data) {
  if (!data) {
    return `<p class="empty-note">没有用量数据。</p>`;
  }
  const total = data.total_calls ?? 0;
  const totalLatency = data.total_latency_ms ?? 0;
  const avgLatency = total > 0 ? (totalLatency / total).toFixed(0) : 0;
  const records = Array.isArray(data.recent) ? data.recent.slice(0, 20) : [];

  const escapeHtml = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

  const statsHtml = `
    <div class="usage-stats">
      <div class="metric-card"><span>总调用数</span><strong>${escapeHtml(total)}</strong></div>
      <div class="metric-card"><span>总延迟</span><strong>${escapeHtml(totalLatency)}ms</strong></div>
      <div class="metric-card"><span>平均延迟</span><strong>${escapeHtml(avgLatency)}ms</strong></div>
    </div>
  `;

  if (records.length === 0) {
    return `${statsHtml}<p class="empty-note">暂无调用记录。</p>`;
  }

  const rowsHtml = records.map((r) => `
    <tr>
      <td>${escapeHtml(r.endpoint || "")}</td>
      <td>${escapeHtml(r.method || "")}</td>
      <td>${r.latency_ms != null ? escapeHtml(r.latency_ms) + "ms" : ""}</td>
      <td>${escapeHtml(r.timestamp || "")}</td>
    </tr>
  `).join("");

  return `${statsHtml}
    <div class="usage-table-wrap">
      <table class="usage-table">
        <thead><tr><th>端点</th><th>方法</th><th>延迟</th><th>时间</th></tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;
}

export function closeUtilityDrawer() {
  utilityDrawer.classList.add("hidden");
  utilityDrawer.setAttribute("aria-hidden", "true");
  if (openToolsButton) {
    openToolsButton.classList.remove("active");
    openToolsButton.setAttribute("aria-expanded", "false");
  }
}
