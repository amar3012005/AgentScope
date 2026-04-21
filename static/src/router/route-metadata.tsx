import type { SVGProps } from "react";
import type { RouteMeta } from "./types";

function makeIcon(path: string) {
  return function Icon(props: SVGProps<SVGSVGElement>) {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
        <path d={path} />
      </svg>
    );
  };
}

const OverviewIcon = makeIcon("M4 5h16v14H4zM9 5v14M15 10h5");
const ChatIcon = makeIcon("M4 5h16v10H8l-4 4V5z");
const RunsIcon = makeIcon("M6 7h5M6 12h12M6 17h9");
const ArtifactIcon = makeIcon("M7 3h7l5 5v13H7zM14 3v5h5");
const UploadIcon = makeIcon("M12 16V7M8.5 10.5 12 7l3.5 3.5M5 19h14");
const AgentIcon = makeIcon("M12 12a3 3 0 1 0-3-3 3 3 0 0 0 3 3zm-7 8a7 7 0 0 1 14 0M19 7h2M20 5v4M3 7h2M4 5v4");
const SettingsIcon = makeIcon("M12 8.5A3.5 3.5 0 1 1 8.5 12 3.5 3.5 0 0 1 12 8.5zm8 3.5-1.8-.6-.4-1.1 1-1.6-1.8-1.8-1.6 1-.9-.4L14 4h-4l-.5 1.9-.9.4-1.6-1-1.8 1.8 1 1.6-.4 1.1L4 12l.6 2 .4 1.1-1 1.6 1.8 1.8 1.6-1 .9.4L10 20h4l.5-1.9.9-.4 1.6 1 1.8-1.8-1-1.6.4-1.1L20 12z");

export const routeMetadata: RouteMeta[] = [
  {
    id: "overview",
    path: "/overview",
    label: "Overview",
    shortLabel: "Overview",
    title: "Executive Overview",
    eyebrow: "Control Room",
    description: "Recent activity, workflow health, and the current shape of the multi-agent system.",
    navGroup: "workspace",
    order: 1,
    accent: "ochre",
    icon: OverviewIcon,
  },
  {
    id: "chat",
    path: "/chat",
    label: "Chat",
    shortLabel: "Chat",
    title: "Orchestration Workspace",
    eyebrow: "Primary Surface",
    description: "Run agentic workflows, answer HITL prompts, and preview Vangogh artifacts in one place.",
    navGroup: "workspace",
    order: 2,
    accent: "azure",
    icon: ChatIcon,
  },
  {
    id: "workflows",
    path: "/workflows",
    label: "Workflows",
    shortLabel: "Runs",
    title: "Workflow History",
    eyebrow: "Thread View",
    description: "Inspect recent workflow threads, execution state, and jump into any run detail view.",
    navGroup: "workspace",
    order: 3,
    accent: "olive",
    icon: RunsIcon,
  },
  {
    id: "artifacts",
    path: "/artifacts",
    label: "Artifacts",
    shortLabel: "Artifacts",
    title: "Artifact Detail",
    eyebrow: "Vangogh Output",
    description: "Review rendered artifacts, preview output, and jump back into workflow regeneration.",
    navGroup: "workspace",
    order: 4,
    accent: "wine",
    icon: ArtifactIcon,
  },
  {
    id: "uploads",
    path: "/uploads",
    label: "Uploads",
    shortLabel: "Uploads",
    title: "Knowledge Uploads",
    eyebrow: "Ingestion",
    description: "Track uploaded knowledge sources and keep the system ready for GraphRAG retrieval.",
    navGroup: "knowledge",
    order: 5,
    accent: "umber",
    icon: UploadIcon,
  },
  {
    id: "agents",
    path: "/agents",
    label: "Agents",
    shortLabel: "Agents",
    title: "Agent Network",
    eyebrow: "Runtime Topology",
    description: "See every registered agent, its protocol, capabilities, and current runtime wiring.",
    navGroup: "system",
    order: 6,
    accent: "azure",
    icon: AgentIcon,
  },
  {
    id: "settings",
    path: "/settings",
    label: "Settings",
    shortLabel: "Settings",
    title: "Workspace Settings",
    eyebrow: "Configuration",
    description: "Inspect tenant, API, and interface settings for the React dashboard rollout.",
    navGroup: "system",
    order: 7,
    accent: "olive",
    icon: SettingsIcon,
  },
];

export function getRouteMeta(pathname: string) {
  if (pathname.startsWith("/runs/")) {
    return routeMetadata.find((route) => route.id === "workflows") ?? routeMetadata[0];
  }
  if (pathname.startsWith("/artifacts/")) {
    return routeMetadata.find((route) => route.id === "artifacts") ?? routeMetadata[0];
  }
  return routeMetadata.find((route) => pathname === route.path) ?? routeMetadata[0];
}
