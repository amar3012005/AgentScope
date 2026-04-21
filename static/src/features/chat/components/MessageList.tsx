import type { WorkspaceMessage } from "../../orchestration/types";
import { MarkdownBlock } from "../../../shared/MarkdownBlock";

export function MessageList({ messages }: { messages: WorkspaceMessage[] }) {
  if (!messages.length) {
    return (
      <div className="chat-empty">
        <div className="chat-empty__eyebrow">No active thread</div>
        <h2>Start a workflow to see the orchestration unfold here.</h2>
        <p>Ask for a report, a pitch deck, or a retrieval task. The timeline, governance, and Vangogh preview will update live.</p>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message) => (
        <article key={message.id} className={`message-card role-${message.role}`}>
          <div className="message-card__meta">
            <span>{message.role === "user" ? "Operator" : message.agentName ?? "BLAIQ"}</span>
            <time>{new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
          </div>
          {message.format === "markdown" ? (
            <MarkdownBlock content={message.content} />
          ) : (
            <div className={`message-card__body format-${message.format}`}>{message.content}</div>
          )}
        </article>
      ))}
    </div>
  );
}
