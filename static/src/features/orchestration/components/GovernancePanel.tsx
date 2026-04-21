import type { GovernanceReport } from "../../../types";

export function GovernancePanel({ report }: { report: GovernanceReport | null }) {
  return (
    <section className="panel-card">
      <div className="panel-card__header">
        <span>Governance</span>
      </div>
      {!report ? (
        <p className="panel-card__empty">Governance output appears after the run reaches review.</p>
      ) : (
        <div className="governance-panel">
          <div className={`governance-panel__badge ${report.validation_passed ? "is-pass" : "is-fail"}`}>
            {report.validation_passed ? "Passed" : "Review needed"}
          </div>
          <ul>
            {report.policy_checks.map((check) => (
              <li key={check.rule}>
                <strong>{check.rule}</strong>
                <span>{check.passed ? "Pass" : check.detail || "Fail"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
