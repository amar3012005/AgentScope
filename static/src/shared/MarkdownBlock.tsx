import DOMPurify from "dompurify";
import { marked } from "marked";

export function MarkdownBlock({ content }: { content: string }) {
  const html = DOMPurify.sanitize(marked.parse(content) as string);
  return <div className="markdown-block" dangerouslySetInnerHTML={{ __html: html }} />;
}
