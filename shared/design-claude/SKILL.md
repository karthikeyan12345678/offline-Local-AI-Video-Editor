---
name: design-system-claude
description: >
  Apply the Claude design system when building or updating UI.
  Use when creating components, choosing colors or typography,
  or reviewing designs for dashboard interfaces.
---

# Claude — Design System Skill

## When to Use

- Building new UI components for Claude.
- Reviewing or updating existing component styles.
- Choosing colors, typography, or spacing for dashboard pages.
- Checking designs against the extracted token set.

## Context

- **Product:** Claude — https://claude.ai/chat/586eb774-b483-46a1-9d77-d21e53255fe1
- **Surface:** dashboard
- **Audience:** Business users and internal teams
- **Character:** Data-driven application interface with a balanced color system and 3 typefaces.

## Tokens

### Colors

| Token | Value | Role |
|-------|-------|------|
| color-2 | `#898781` | Text Secondary |
| color-3 | `#6DA7EC` | Accent |
| color-1 | `#2C2C2A` | Background Dark |
| color-4 | `#C3C2B7` | Text Light |
| color-5 | `#F0EFEC` | Text Light |
| color-6 | `#FFFFFF` | Text Light |

### Typography

**Font stack:** anthropic-sans, Anthropicons-Variable, anthropic-serif

| Level | Size | Usage |
|-------|------|-------|
| text-xs | 9px | Captions, metadata |
| text-sm | 12px | Labels, secondary text |
| text-base | 14px | Body text (default) |
| text-lg | 16px | Subheadings, emphasis |
| text-xl | 20px | Section headings |

**Weight scale:** 400 · 433 · 500 · 533 · 577 · 700
**Line heights:** 20px · 19px · 16px · 21px · 12px · 17px · 13.5px · 18px · 24px

### Spacing

**Base unit:** 4px

`space-1: 1px` · `space-2: 2px` · `space-3: 3px` · `space-4: 4px` · `space-5: 6px` · `space-6: 8px` · `space-7: 10px` · `space-8: 12px` · `space-9: 16px` · `space-10: 18px` · `space-11: 20px` · `space-12: 24px` · `space-13: 40px` · `space-14: 48px` · `space-15: 111px` · `space-16: 130px` · `space-17: 296px`

### Shapes

**Border radius:** `radius-sm: 2px` · `radius-md: 2.68435e+07px` · `radius-lg: 6px` · `radius-xl: 7px` · `radius-full: 8px` · `radius-6: 12px` · `radius-7: 14px` · `radius-8: 24px`

### Elevation

- **shadow-sm:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, color(srgb 1 1 1 / 0.1) 0px 0px 0px 1px inset, color(srgb 1 1 1 / 0.1) 0px 0px 0px 0px, rgba(0, 0, 0, 0.32) 0px 8px 24px 0px, rgba(0, 0, 0, 0.2) 0px 2px 6px 0px`
- **shadow-md:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 1px inset, rgba(0, 0, 0, 0.05) 0px 1px 2px 0px`
- **shadow-lg:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 1px inset`
- **shadow-xl:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, color(srgb 0 0 0 / 0.075) 0px 4px 20px 0px, color(srgb 1 1 1 / 0.2) 0px 0px 0px 1px inset, color(srgb 1 1 1 / 0.2) 0px 0px 0px 0px`
- **shadow-5:** `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgb(21, 21, 21) 0px 0px 0px 32px`

### Motion

- **duration-fast:** `all`
- **duration-fast:** `box-shadow cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-fast:** `none`
- **duration-fast:** `background-color 0.06s cubic-bezier(0.165, 0.84, 0.44, 1), box-shadow 0.06s cubic-bezier(0.165, 0.84, 0.44, 1), color 0.06s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-fast:** `box-shadow 0.06s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-fast:** `text-decoration-color 0.06s cubic-bezier(0.165, 0.84, 0.44, 1), box-shadow 0.06s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-fast:** `box-shadow 0.06s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-fast:** `opacity 0.06s cubic-bezier(0.4, 0, 0.2, 1), visibility 0.06s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-fast:** `filter 0.12s ease-out`
- **duration-fast:** `opacity 0.12s cubic-bezier(0.165, 0.84, 0.44, 1), transform 0.12s cubic-bezier(0.165, 0.84, 0.44, 1), translate 0.12s cubic-bezier(0.165, 0.84, 0.44, 1), margin-right 0.12s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-fast:** `opacity 0.12s cubic-bezier(0.32, 0.72, 0, 1)`
- **duration-base:** `opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1), padding-left 0.2s cubic-bezier(0.4, 0, 0.2, 1), padding-right 0.2s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-base:** `padding-left 0.2s cubic-bezier(0.4, 0, 0.2, 1), padding-right 0.2s cubic-bezier(0.4, 0, 0.2, 1), padding-bottom 0.2s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-base:** `padding-left 0.2s cubic-bezier(0.4, 0, 0.2, 1), padding-right 0.2s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-base:** `background-color 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1)`
- **duration-base:** `opacity 0.2s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-base:** `opacity 0.28s cubic-bezier(0.165, 0.84, 0.44, 1), translate 0.28s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-base:** `grid-template-rows 0.28s cubic-bezier(0.165, 0.84, 0.44, 1)`
- **duration-base:** `--cds-anim 0.3s cubic-bezier(0.34, 1.3, 0.64, 1)`
- **duration-slow:** `transform 0.45s linear(0 0%, 0.2459 7.14286%, 0.6526 14.2857%, 0.9468 21.4286%, 1.0764 28.5714%, 1.0915 35.7143%, 1.0585 42.8571%, 1.0219 50%, 0.9993 57.1429%, 0.9914 64.2857%, 0.9921 71.4286%, 0.9957 78.5714%, 0.9988 85.7143%, 1.0004 92.8571%, 1 100%)`
- **duration-slow:** `2s ease-in-out 1.9263s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.0163s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.1063s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.6463s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.3763s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.2863s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.5563s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.1963s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.8263s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.4663s infinite cds-skeleton-breathe`
- **duration-slow:** `2s ease-in-out 2.7363s infinite cds-skeleton-breathe`

## Component Inventory

- **Buttons:** 17 detected
- **Links:** 9 detected
- **Inputs:** 1 detected
- **Images:** 1 detected

## Constraints

### Always

- Use tokens from the tables above — do not introduce new values.
- Include hover, focus-visible, and disabled states for interactive elements.
- Follow the 4px spacing grid.
- Meet WCAG 2.2 AA contrast minimums.

### Never

- Do not introduce colors outside the extracted palette.
- Do not use arbitrary spacing values — stick to the scale.
- Do not mix border-radius values. Pin to the detected set (2px, 2.68435e+07px, 6px, 7px, 8px, 12px, 14px, 24px).
- Do not use decorative shadows on data-dense layouts.
- Do not hide critical status information behind interactions.
- Do not ship components without defining hover, focus-visible, and disabled states.

## Tone

Efficient, data-forward, action-oriented. Labels over sentences.

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
