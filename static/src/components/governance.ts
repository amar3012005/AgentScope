import { createElement, escapeHtml } from "../utils/dom";
import type { GovernanceReport, PolicyCheck } from "../types";

let container: HTMLElement | null = null;
let expanded = false;

function createCheckRow(check: PolicyCheck): HTMLElement {
  const row = createElement("div", { class: "governance-check-row" });

  const icon = createElement("div", {
    class: `governance-check-icon governance-check-icon--${check.passed ? "passed" : "failed"}`,
  }, [check.passed ? "\u2713" : "\u2717"]);

  const content = createElement("div", { class: "governance-check-content" });
  const rule = createElement("div", { class: "governance-check-rule" }, [escapeHtml(check.rule)]);
  const detail = createElement("div", { class: "governance-check-detail" }, [
    escapeHtml(check.detail),
  ]);

  content.appendChild(rule);
  content.appendChild(detail);
  row.appendChild(icon);
  row.appendChild(content);

  return row;
}

export function mountGovernance(containerEl: HTMLElement): void {
  container = containerEl;
}

export function show(report: GovernanceReport | null | undefined): void {
  if (!container || !report) return;
  container.innerHTML = "";
  expanded = false;

  const totalChecks = report.policy_checks.length;
  const passedChecks = report.policy_checks.filter((c) => c.passed).length;

  const badgeClass = report.validation_passed
    ? "governance-badge governance-badge--passed"
    : "governance-badge governance-badge--failed";

  const badgeText = report.validation_passed
    ? `Governance Passed (${passedChecks}/${totalChecks})`
    : `${totalChecks - passedChecks} violation(s)`;

  const badgeIcon = report.validation_passed ? "\u2705" : "\u26A0\uFE0F";

  const badge = createElement("button", { class: badgeClass, type: "button" });
  const iconSpan = createElement("span", { class: "governance-badge-icon" }, [badgeIcon]);
  badge.appendChild(iconSpan);
  badge.appendChild(document.createTextNode(badgeText));

  const detailPanel = createElement("div", {
    class: "governance-detail",
    style: "display:none",
  });

  const detailHeader = createElement("div", { class: "governance-detail-header" });
  const detailTitle = createElement("div", { class: "governance-detail-title" }, [
    "Policy Checks",
  ]);
  const closeBtn = createElement("button", {
    class: "governance-detail-close",
    type: "button",
    "aria-label": "Close governance details",
  }, ["\u00D7"]);
  detailHeader.appendChild(detailTitle);
  detailHeader.appendChild(closeBtn);

  const checksContainer = createElement("div", { class: "governance-checks" });
  for (const check of report.policy_checks) {
    checksContainer.appendChild(createCheckRow(check));
  }

  detailPanel.appendChild(detailHeader);
  detailPanel.appendChild(checksContainer);

  if (report.violations.length > 0) {
    const violationsSection = createElement("div", { class: "governance-violations" });
    const violationsLabel = createElement("div", { class: "governance-violations-label" }, [
      "Violations",
    ]);
    violationsSection.appendChild(violationsLabel);

    for (const v of report.violations) {
      const item = createElement("div", { class: "governance-violation-item" }, [escapeHtml(v)]);
      violationsSection.appendChild(item);
    }
    detailPanel.appendChild(violationsSection);
  }

  badge.addEventListener("click", () => {
    expanded = !expanded;
    detailPanel.style.display = expanded ? "block" : "none";
  });

  closeBtn.addEventListener("click", () => {
    expanded = false;
    detailPanel.style.display = "none";
  });

  container.appendChild(badge);
  container.appendChild(detailPanel);
}

export function hide(): void {
  if (container) {
    container.innerHTML = "";
  }
}
