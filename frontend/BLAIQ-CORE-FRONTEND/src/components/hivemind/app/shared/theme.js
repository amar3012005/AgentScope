/**
 * HIVEMIND Design Tokens
 * Supermemory-inspired warm light console aesthetic
 * Accent: blue (#117dff) — clean, professional
 */

export const colors = {
  // Base - warm cream/off-white like Supermemory
  bg: {
    primary: '#faf9f4',
    secondary: '#f3f1ec',
    tertiary: '#eae7e1',
    elevated: '#ffffff',
    surface: '#f3f1ec',
    hover: '#eae7e1',
    active: '#e3e0db',
  },
  // Accent
  accent: {
    primary: '#117dff',
    primaryHover: '#0066e0',
    primaryMuted: 'rgba(17, 125, 255, 0.08)',
    primaryGlow: 'rgba(17, 125, 255, 0.15)',
  },
  // Text
  text: {
    primary: '#0a0a0a',
    secondary: '#525252',
    tertiary: '#737373',
    muted: '#a3a3a3',
    inverse: '#ffffff',
  },
  // Borders - warm gray like Supermemory
  border: {
    subtle: '#eae7e1',
    default: '#e3e0db',
    strong: '#d4d0ca',
    accent: 'rgba(17, 125, 255, 0.25)',
  },
  // Status
  status: {
    success: '#16a34a',
    warning: '#d97706',
    error: '#dc2626',
    info: '#2563eb',
  },
};

export const fonts = {
  display: "'Space Grotesk', sans-serif",
  body: "Inter, ui-sans-serif, system-ui, sans-serif",
  mono: "'JetBrains Mono', 'Fira Code', monospace",
};

export const shadows = {
  card: '0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02)',
  elevated: '0 4px 12px rgba(0, 0, 0, 0.06)',
  glow: '0 0 20px rgba(17, 125, 255, 0.08)',
  glowStrong: '0 0 40px rgba(17, 125, 255, 0.15)',
};

// API endpoints resolved from bootstrap
export const API_DEFAULTS = {
  controlPlaneBase: process.env.REACT_APP_CONTROL_PLANE_URL || 'https://api.hivemind.davinciai.eu:8040',
  coreApiBase: process.env.REACT_APP_CORE_API_URL || 'https://core.hivemind.davinciai.eu:8050',
};
