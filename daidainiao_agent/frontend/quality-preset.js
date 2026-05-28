import { saveSettings } from "./state.js";

export function applyQualityPreset(settings, preset) {
  const next = { ...settings, qualityPreset: preset === "fast" ? "fast" : "accurate" };
  if (preset === "fast") {
    next.useRerank = false;
    next.selfCorrect = false;
    next.topK = Math.min(next.topK || 5, 4);
  } else {
    next.useRerank = true;
    next.selfCorrect = true;
  }
  return saveSettings(next);
}

export function getEffectiveAskOptions(settings) {
  const preset = settings.qualityPreset === "fast" ? "fast" : "accurate";
  if (preset === "fast") {
    return {
      top_k: Math.min(Number(settings.topK) || 5, 4),
      strict_grounded: settings.strictGrounded !== false,
      use_rerank: false,
      self_correct: false,
    };
  }
  return {
    top_k: Number(settings.topK) || 5,
    strict_grounded: settings.strictGrounded !== false,
    use_rerank: settings.useRerank !== false,
    self_correct: settings.selfCorrect !== false,
  };
}
