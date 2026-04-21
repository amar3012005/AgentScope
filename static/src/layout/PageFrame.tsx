import type { ReactNode } from "react";

interface PageFrameProps {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function PageFrame({
  eyebrow,
  title,
  description,
  actions,
  className,
  children,
}: PageFrameProps): JSX.Element {
  return (
    <div className={className ? `page-frame ${className}` : "page-frame"}>
      <header className="page-frame__hero">
        <div className="page-frame__copy">
          <p className="page-frame__eyebrow">{eyebrow}</p>
          <h1 className="page-frame__title">{title}</h1>
          <p className="page-frame__description">{description}</p>
        </div>
        {actions ? <div className="page-frame__actions">{actions}</div> : null}
      </header>
      <div className="page-frame__body">{children}</div>
    </div>
  );
}
