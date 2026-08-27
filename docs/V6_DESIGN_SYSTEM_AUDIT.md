# Lead Radar V6 — Design System & Visual Tokens Audit Report

## 1. Visual Language & Reference Direction
- Premium smart control center with translucent glass panels (`backdrop-filter: blur(12px)`), subtle borders, soft shadows, warm neutral background, and clean typography.
- High information density with compact spacing scale.

## 2. Design Tokens Matrix
```css
:root {
  /* Surfaces & Glass */
  --bg-app: #0f141c;
  --panel-bg: rgba(22, 30, 44, 0.75);
  --panel-border: rgba(255, 255, 255, 0.08);
  --glass-blur: 14px;
  --shadow-soft: 0 8px 32px rgba(0, 0, 0, 0.25);

  /* Typography */
  --font-family-base: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-size-title: 28px;
  --font-size-heading: 20px;
  --font-size-card: 16px;
  --font-size-body: 15px;
  --font-size-sub: 13px;

  /* Accents & Statuses */
  --accent-primary: #3b82f6;
  --accent-hover: #2563eb;
  --status-hot: #ef4444;
  --status-good: #10b981;
  --status-warn: #f59e0b;
  --status-info: #3b82f6;

  /* Spacing & Radii */
  --radius-panel: 14px;
  --radius-card: 10px;
  --radius-btn: 8px;
}
```

## 3. Accessibility & Motion Rules
- Focus Outlines: `:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }`
- Touch Targets: Minimum 44px height for interactive buttons on mobile.
- Motion Durations: 140ms hover, 200ms card expand, 250ms drawer/modal.
- Respect `prefers-reduced-motion` to disable non-essential animations.
