import { useEffect, useRef } from "react";
import type { SectionFragment } from "../../../shared/orchestrator/types";

interface CodeStreamPaneProps {
  sections: SectionFragment[];
  fullHtml: string;
}

export function CodeStreamPane({ sections, fullHtml }: CodeStreamPaneProps) {
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [sections.length, fullHtml]);

  const codeContent =
    sections.length > 0
      ? sections
          .map(
            (s) =>
              `<!-- ═══ Section: ${s.label} (${s.sectionId}) ═══ -->\n${s.htmlFragment}`
          )
          .join("\n\n")
      : fullHtml;

  return (
    <div className="code-stream">
      <div className="code-stream__header">
        <span className="code-stream__label">HTML Source</span>
        {sections.length > 0 && (
          <span className="code-stream__count">
            {sections.length} section{sections.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      <pre ref={preRef} className="code-stream__code">
        <code>{codeContent}</code>
      </pre>
    </div>
  );
}
