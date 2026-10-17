import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../shared/design/tokens.css";
import "../../shared/design/components.css";
import "./app.css";
import App from "./App";
import SiteApp from "./site/SiteApp";

// The dark "Studio" look is the default; people who chose Classic in Settings keep it.
document.documentElement.dataset.look = "studio";
try { if (localStorage.getItem("vk_look") === "classic") delete document.documentElement.dataset.look; } catch { /* storage blocked: Studio look */ }

const boot = () => createRoot(document.getElementById("root")!).render(<StrictMode>{import.meta.env.VITE_WEB === "1" ? <SiteApp /> : <App />}</StrictMode>);
if (import.meta.env.VITE_WEB === "1") void import("./web/fonts").then((m) => m.loadFontTable()).finally(boot); else boot();
