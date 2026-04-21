import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          bg: "var(--brand-bg, #050505)",
          surface: "var(--brand-surface, #111111)",
          border: "var(--brand-border, #2A2A2A)",
          primary: "var(--brand-primary, #F5F5F1)",
          accent: "var(--brand-accent, #6c63ff)",
          accent2: "var(--brand-accent2, #ff6584)",
          muted: "var(--brand-muted, #A1A19B)",
          ink: "var(--brand-ink, #E8E7E2)",
        },
      },
      fontFamily: {
        heading: ["var(--brand-font-heading, 'Inter')", "system-ui", "sans-serif"],
        body: ["var(--brand-font-body, 'Inter')", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
