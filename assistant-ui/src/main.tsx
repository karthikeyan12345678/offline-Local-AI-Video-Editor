import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../shared/design-claude/tokens.css";
import "../../shared/design-claude/components.css";
import "./app.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
