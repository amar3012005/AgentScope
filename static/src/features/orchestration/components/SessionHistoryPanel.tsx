import { Link } from "react-router-dom";
import type { RunRecord } from "../types";

export function SessionHistoryPanel({
  runs,
  recentThreadIds,
  activeThreadId,
  onSelect,
}: {
  runs: Record<string, RunRecord>;
  recentThreadIds: string[];
  activeThreadId: string;
  onSelect: (threadId: string) => void;
}) {
  return (
    <section className="panel-card">
      <div className="panel-card__header">
        <span>Recent Runs</span>
      </div>
      <div className="history-list">
        {recentThreadIds.length === 0 ? (
          <p className="panel-card__empty">No workflow history yet.</p>
        ) : (
          recentThreadIds.map((threadId) => {
            const run = runs[threadId];
            const title = run?.userQuery || threadId;
            return (
              <button
                key={threadId}
                type="button"
                className={`history-item${threadId === activeThreadId ? " is-active" : ""}`}
                onClick={() => onSelect(threadId)}
              >
                <div className="history-item__title">{title}</div>
                <div className="history-item__meta">
                  <span>{run?.status ?? "unknown"}</span>
                  <Link to={`/runs/${threadId}`}>Detail</Link>
                </div>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
