# Claude design system (shared)

Tokens and framework-free component CSS for the AI Assistant UI, built from `DESIGN.md` / `SKILL.md` (the extracted Claude dark theme).

- `tokens.json` -> `node build-tokens.mjs` -> `tokens.css` (generated, do not edit).
- `components.css` uses tokens only.

Deliberate decisions (documented because the source tokens could not be used literally):
- **9px caption size is not used.** Smallest text is 12px for readability (WCAG 1.4.4/1.4.12 practice).
- **`color-2` (#898781) is 3.9:1 on the background**, below AA for text, so it is restricted to disabled states and decoration. Secondary text uses `color-4` (#C3C2B7, 7.8:1).
- **Accent text only on the base background** (5.6:1). On raised surfaces the accent is used for borders/focus, text stays `color-5`.
- **Raised surfaces are white overlays (5%/10%/16%)** on the base colour, matching the source system's own white-inset shadows; no new hues are introduced.
- Radii are limited to 6/8/12/14/24/pill and spacing to the 4px grid (4, 8, 12, 16, 20, 24, 40, 48).
- Status (error/info) is never colour-only: errors use a 2px outline plus an icon and bold label.
