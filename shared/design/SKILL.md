---
name: design-system-chatgpt
description: >
  Apply the ChatGPT design system when building or updating UI.
  Use when creating components, choosing colors or typography,
  or reviewing designs for marketing interfaces.
---

# ChatGPT — Design System Skill

## When to Use

- Building new UI components for ChatGPT.
- Reviewing or updating existing component styles.
- Choosing colors, typography, or spacing for marketing pages.
- Checking designs against the extracted token set.

## Context

- **Product:** ChatGPT — https://chatgpt.com/?utm_source=google&utm_medium=paid_search&gbraid=0AAAAA-I0E5fASpW7SPedTrBZr1QrKA-ud&gclid=CjwKCAjw0LzWBhBOEiwAKQd0cLJF4rUo_F6q4FBvL3s0xLkxXuQlE7GH9qLFCx8s7zAx-NUwFLzVwBoCuDQQAvD_BwE&c_id=22243298608&c_crid=783405695218&c_agid=176486812938&c_kwid=kwd-2089546592128
- **Surface:** marketing
- **Audience:** Business decision-makers and potential customers
- **Character:** Conversion-focused marketing presence with a rich, diverse color palette and single-typeface typography.

## Tokens

### Colors

| Token | Value | Role |
|-------|-------|------|
| --color-text-execution-output-label | `#B4B4B4` | Text Light |
| color-7 | `#FFFFFF` | Background |
| color-1 | `#0D0D0D` | Text Primary |
| color-2 | `#2C67C5` | Accent |
| color-3 | `#AFAFAF` | Text Light |
| color-5 | `#CDCDCD` | Text Light |
| color-6 | `#EDEDED` | Text Light |

### Typography

**Font stack:** -apple-system-body

| Level | Size | Usage |
|-------|------|-------|
| text-xs | 12px | Captions, metadata |
| text-sm | 14px | Labels, secondary text |
| text-base | 16px | Body text (default) |
| text-lg | 18px | Subheadings, emphasis |
| text-xl | 24px | Section headings |

**Weight scale:** 400 · 500 · 600
**Line heights:** 28.8px · 26px · 14px · 20px · 18px · 12px · 24px · 16px

### Spacing

**Base unit:** 4px

`space-1: 1px` · `space-2: 2px` · `space-3: 3px` · `space-4: 4px` · `space-5: 6px` · `space-6: 8px` · `space-7: 10px` · `space-8: 14px` · `space-9: 16px` · `space-10: 20px` · `space-11: 64px` · `space-12: 251px`

### Shapes

**Border radius:** `radius-sm: 4px` · `radius-md: 6px` · `radius-lg: 8px` · `radius-xl: 26px` · `radius-full: 9999px`

### Elevation

- **shadow-sm:** `rgba(255, 255, 255, 0.2) 0px 0px 1px 0px inset`

### Motion

- **duration-fast:** `all`
- **duration-fast:** `none`
- **duration-fast:** `opacity 0.15s 0.1s`
- **duration-fast:** `opacity 0.15s, color 0.15s`
- **duration-fast:** `opacity 0.15s linear`
- **duration-fast:** `opacity 0.15s cubic-bezier(0.4, 0, 0.2, 1)`

## Component Inventory

- **Buttons:** 57 detected
- **Links:** 16 detected
- **Inputs:** 4 detected
- **Navigation:** 2 elements
- **Forms:** 1 detected
- **Images:** 61 detected

## Constraints

### Always

- Use tokens from the tables above — do not introduce new values.
- Include hover, focus-visible, and disabled states for interactive elements.
- Follow the 4px spacing grid.
- Meet WCAG 2.2 AA contrast minimums.

### Never

- Do not introduce colors outside the extracted palette.
- Do not use arbitrary spacing values — stick to the scale.
- Do not mix border-radius values. Pin to the detected set (4px, 6px, 8px, 26px, 9999px).
- Do not use full-uppercase text for body or paragraph content.
- Do not nest interactive elements (e.g. buttons inside links).
- Do not ship components without defining hover, focus-visible, and disabled states.

## Tone

Concise, confident, implementation-focused. Avoid filler preambles.

## Authoring Workflow

When creating or documenting a component for this system:

1. State intent — one sentence on purpose.
2. Map tokens — list every token the component uses.
3. Define anatomy — named parts with token assignments.
4. Specify states — default, hover, focus-visible, active, disabled, loading, error, empty.
5. Describe interactions — keyboard, pointer, touch, edge cases.
6. Add a11y criteria — testable pass/fail checks.
7. List anti-patterns — concrete misuse examples.
8. Close with the Definition of Done checklist.

## Output Structure

Component guidelines must contain, in order:

1. Overview (purpose, when to use, when not to use)
2. Tokens and foundations
3. Anatomy, variants, responsive behavior
4. States and interactions
5. Accessibility (ARIA, contrast, focus, screen reader)
6. Content guidelines (copy rules, tone)
7. Anti-patterns with reasoning

## Component Requirements

- Reference only tokens from the tables above.
- Define all states: default, hover, focus-visible, active, disabled, loading, error.
- Handle edge cases: empty, overflow, truncation, max content.
- Include keyboard navigation behavior.
- Document ARIA roles and labels.

## Definition of Done

- Default state renders (smoke test).
- All states visually verified.
- Zero hardcoded visual values — tokens only.
- Keyboard navigation works without pointer.
- No critical a11y violations.
- Tested at min and max breakpoint.
- At least one anti-pattern documented.
- Purpose, usage, and limitations documented.
