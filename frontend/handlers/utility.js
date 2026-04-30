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

export function closeUtilityDrawer() {
  utilityDrawer.classList.add("hidden");
  utilityDrawer.setAttribute("aria-hidden", "true");
  if (openToolsButton) {
    openToolsButton.classList.remove("active");
    openToolsButton.setAttribute("aria-expanded", "false");
  }
}
