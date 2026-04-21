import type { ComponentType, SVGProps } from "react";

export type RouteAccent = "umber" | "ochre" | "olive" | "wine" | "azure";

export interface RouteMeta {
  id: "overview" | "chat" | "workflows" | "artifacts" | "uploads" | "agents" | "settings";
  path: string;
  label: string;
  shortLabel: string;
  title: string;
  eyebrow: string;
  description: string;
  navGroup: "workspace" | "knowledge" | "system";
  order: number;
  accent: RouteAccent;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}
