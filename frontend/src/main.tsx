import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../shared/design/tokens.css";
import "../../shared/design/components.css";
import "./app.css";
import App from "./App";

try { const l = localStorage.getItem("vk_look"); if (l === "kling") document.documentElement.dataset.look = "kling"; } catch { /* storage blocked: classic look */ }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
