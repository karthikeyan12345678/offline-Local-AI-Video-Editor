# Shared design system

One folder, used by every project that should look the same. It is plain CSS and JSON, so it works with React, Vue, plain HTML or Electron.

| File | What it is |
|---|---|
| `tokens.json` | The single source of truth: colours, type scale, spacing, radii, shadow, motion. |
| `tokens.css` | Generated from `tokens.json` as CSS variables (`--color-accent`, `--space-6` …). Never edit by hand. |
| `components.css` | Ready-made classes: `.btn`, `.field`, `.input`, `.select`, `.range`, `.check`, `.card`, `.badge`, `.tabs`, `.progress`, `.dialog`, `.toast`, `.empty` … They only read tokens. |
| `DESIGN.md`, `SKILL.md` | The written rules (palette, 4 px grid, states, accessibility). Give these to a designer or to Claude when building a new screen. |

## Use it in another project

Copy this folder, or install it as a package (`npm i ../shared/design`), then import the two stylesheets once, tokens first:

```js
import "chatgpt-design-system/tokens.css";
import "chatgpt-design-system/components.css";
```

```html
<link rel="stylesheet" href="design/tokens.css">
<link rel="stylesheet" href="design/components.css">
<button class="btn">Save</button>
<button class="btn btn--secondary">Cancel</button>
```

## Change the look everywhere

1. Edit `tokens.json`.
2. Run `node build-tokens.mjs` (rewrites `tokens.css`).
3. Rebuild each app. Nothing else needs touching because no app hard-codes a colour, spacing or radius.

## Rules the components follow

- Tokens only. No raw colours, pixel spacings or radii in app code.
- The palette has no red or green, so **errors** are shown with a heavy dark border, bold message and an icon, never by colour alone.
- **Focus** is a 2 px accent outline on every interactive element.
- **Disabled** controls are grey on light grey with a not-allowed cursor.
- The light grey used for placeholders (`--color-gray-4`) is below WCAG contrast on white. Use it only for hints that are also available elsewhere, never for essential text.

## Where it is used

- `frontend/` imports both stylesheets in `src/main.tsx`.
- `electron/splash.html` loads staged copies (`scripts/stage-electron.mjs` copies them before packaging).
