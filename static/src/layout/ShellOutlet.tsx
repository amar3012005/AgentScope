import type { PropsWithChildren } from "react";

export function ShellOutlet({ children }: PropsWithChildren) {
  return <section className="page-frame">{children}</section>;
}
