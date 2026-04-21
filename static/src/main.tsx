import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles/theme.css";
import "./styles/reset.css";
import "./styles/typography.css";
import "./styles/app.css";
import "./styles/layout.css";
import "./styles/animations.css";
import "./styles/components/sidebar.css";
import "./styles/components/topbar.css";
import "./styles/components/page-frame.css";
import "./styles/components/messages.css";
import "./styles/components/input.css";
import "./styles/components/timeline.css";
import "./styles/components/governance.css";
import "./styles/components/artifact.css";
import "./styles/components/schema.css";
import "./styles/components/session.css";
import "./styles/components/upload.css";
import "./styles/components/welcome.css";
import "./styles/responsive.css";

const container = document.getElementById("app");

if (!container) {
  throw new Error('Missing root element with id "app".');
}

const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

createRoot(container).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </StrictMode>
);
