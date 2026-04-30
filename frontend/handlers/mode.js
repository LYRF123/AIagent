import {
  getCurrentMode,
  setCurrentMode,
  getIsSubmitting,
  setIsSubmitting,
  getCurrentSessionId,
  modeLabels,
  submitLabels,
  modeButtons,
  modeFields,
  presetButtons,
  form,
  submitButton,
  modeBadge,
  strictGroundedInput,
  useRagasInput,
  topKInput,
  candidateKInput,
  ragRerankInput,
  ragCompareConfigsInput,
  detailOutput,
  jsonOutput,
} from "../state.js";
import { setStatus, renderEmptySummary } from "../render/common.js";
import { renderResult } from "../render/results.js";
import { runAskModeStream } from "../stream.js";
import { closeUtilityDrawer } from "./utility.js";

export function setFormBusy(nextIsSubmitting) {
  setIsSubmitting(nextIsSubmitting);
  submitButton.disabled = nextIsSubmitting;
  submitButton.setAttribute("aria-busy", String(nextIsSubmitting));
  form.classList.toggle("is-busy", nextIsSubmitting);
  modeButtons.forEach((button) => {
    button.disabled = nextIsSubmitting;
  });
  presetButtons.forEach((button) => {
    button.disabled = nextIsSubmitting;
  });
}

export function showMode(mode) {
  const nextMode = modeLabels[mode] ? mode : "ask";
  setCurrentMode(nextMode);
  modeButtons.forEach((button) => {
    const isActive = button.dataset.mode === nextMode;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
  modeFields.forEach((field) => {
    field.classList.toggle("hidden", field.dataset.mode !== nextMode);
  });
  submitButton.textContent = submitLabels[nextMode] || `\u8FD0\u884C${modeLabels[nextMode]}`;
  modeBadge.textContent = `\u5F53\u524D\u6A21\u5F0F\uFF1A${modeLabels[nextMode]}`;
}

export function buildPayload(mode) {
  const topK = Number(topKInput?.value || 5);
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
        session_id: getCurrentSessionId() || undefined,
        strict_grounded: strictGroundedInput.checked,
      },
    };
  }
  if (mode === "rag_lab") {
    const candidateK = Number(candidateKInput?.value || Math.max(topK * 4, topK));
    const rerank = Boolean(ragRerankInput?.checked);
    const compareConfigs = ragCompareConfigsInput?.checked !== false;
    const configs = compareConfigs
      ? [
        { name: "rerank_on", top_k: topK, candidate_k: candidateK, use_rerank: true },
        { name: "rerank_off", top_k: topK, candidate_k: candidateK, use_rerank: false },
      ]
      : [
        { name: rerank ? "rerank_on" : "rerank_off", top_k: topK, candidate_k: candidateK, use_rerank: rerank },
      ];
    return {
      endpoint: "/rag-lab/evaluate",
      payload: {
        top_k: topK,
        candidate_k: candidateK,
        use_rerank: rerank,
        configs,
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
      use_ragas: Boolean(useRagasInput?.checked),
    },
  };
}

export async function runMode(mode) {
  if (getIsSubmitting()) {
    return;
  }

  const { endpoint, payload } = buildPayload(mode);
  setFormBusy(true);
  try {
    if (mode === "ask") {
      try {
        await runAskModeStream(payload);
      } catch (error) {
        setStatus("\u8BF7\u6C42\u5931\u8D25", "error");
        renderEmptySummary("\u8BF7\u6C42\u5931\u8D25", error.message || "\u53D1\u751F\u672A\u77E5\u9519\u8BEF");
        detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u68C0\u67E5\u8F93\u5165\u5185\u5BB9\u6216\u540E\u7AEF\u670D\u52A1\u72B6\u6001\u3002</p>`;
        jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
      }
      return;
    }

    setStatus(`\u6B63\u5728\u8FD0\u884C${modeLabels[mode]}...`, "loading");
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
        throw new Error(data.error || `\u8BF7\u6C42\u5931\u8D25\uFF1A${response.status}`);
      }
      setStatus(`${modeLabels[mode]}\u5B8C\u6210`, "success");
      renderResult(mode, data);
      jsonOutput.textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      setStatus("\u8BF7\u6C42\u5931\u8D25", "error");
      renderEmptySummary("\u8BF7\u6C42\u5931\u8D25", error.message || "\u53D1\u751F\u672A\u77E5\u9519\u8BEF");
      detailOutput.innerHTML = `<p class="empty-note">\u8BF7\u68C0\u67E5\u8F93\u5165\u5185\u5BB9\u6216\u540E\u7AEF\u670D\u52A1\u72B6\u6001\u3002</p>`;
      jsonOutput.textContent = JSON.stringify({ error: error.message }, null, 2);
    }
  } finally {
    setFormBusy(false);
  }
}

export function applyPreset(name) {
  if (name === "ask-react") {
    showMode("ask");
    document.getElementById("ask-question").value = "ReAct \u662F\u5982\u4F55\u628A\u63A8\u7406\u548C\u5DE5\u5177\u8C03\u7528\u7ED3\u5408\u8D77\u6765\u7684\uFF1F";
    closeUtilityDrawer();
    return;
  }
  if (name === "ask-model") {
    showMode("ask");
    document.getElementById("ask-question").value = "\u4F60\u662F\u4EC0\u4E48\u6A21\u578B\uFF1F";
    closeUtilityDrawer();
    return;
  }
  showMode("rag_lab");
  if (topKInput) {
    topKInput.value = "5";
  }
  if (candidateKInput) {
    candidateKInput.value = "20";
  }
  if (ragRerankInput) {
    ragRerankInput.checked = true;
  }
  if (ragCompareConfigsInput) {
    ragCompareConfigsInput.checked = true;
  }
  closeUtilityDrawer();
}
