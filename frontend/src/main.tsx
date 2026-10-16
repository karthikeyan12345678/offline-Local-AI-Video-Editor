import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../shared/design/tokens.css";
import "../../shared/design/components.css";
import "./app.css";
import App from "./App";

// The dark "Studio" look is the default; people who chose Classic in Settings keep it.
document.documentElement.dataset.look = "studio";
try { if (localStorage.getItem("vk_look") === "classic") delete document.documentElement.dataset.look; } catch { /* storage blocked: Studio look */ }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
