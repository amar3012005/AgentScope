import type { TimelineEntry } from "../types";

export function ExecutionTimelinePanel({ timeline }: { timeline: TimelineEntry[] }) {
  return (
    <section className="panel-card">
      <div className="panel-card__header">
        <span>Execution Timeline</span>
      </div>
      <div className="timeline-list">
        {timeline.length === 0 ? (
          <p className="panel-card__empty">No orchestration steps yet.</p>
        ) : (
          timeline.map((entry) => (
            <div key={entry.id} className={`timeline-item status-${entry.status}`}>
              <div className="timeline-item__dot" />
              <div>
                <div className="timeline-item__label">{entry.label}</div>
                <div className="timeline-item__time">{new Date(entry.timestamp).toLocaleTimeString()}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
