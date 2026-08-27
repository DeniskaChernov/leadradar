# Lead Radar V6 — Comprehensive UI/UX Audit & Design System Specification

## 1. Executive Summary & Visual North Star

This audit establishes the foundation for transforming Lead Radar from a traditional web dashboard into a **VisionOS-inspired Premium AI Control Center**. Grounded in the reference design, the interface features a floating liquid-glass container (`.glass-shell`) over an ambient blurred interior background, utilizing backdrop blur (`backdrop-filter: blur(40px)`), frosted glass cards (`.glass-card`), high-contrast typography, and strict spacing tokens.

---

## 2. Current Frontend Architecture Analysis

- **Templates**: Jinja2 templates (`base.html`, `index.html`, `leads.html`, `lead_detail.html`, `audiences.html`, `competitors.html`, `openings.html`).
- **Styling**: Vanilla CSS in `app/web/static/app.css`.
- **JavaScript**: Modular client-side JS in `app/web/static/app.js` handling toasts, confirmations, search, and Telegram WebApp integration.
- **Iconography**: Lucide icons (`data-lucide="..."`).

---

## 3. Identified UI/UX Pain Points & Improvements

| Area | Previous State | New Liquid-Glass Specification |
|---|---|---|
| **Background** | Flat solid/gradient `#071019` | Blurred photographic interior background with warm ambient light + darkening overlay |
| **Containers** | Rectangular dark panels with hard borders | Floating rounded `.glass-shell` (32px radius) + `.glass-card` (20px radius) with soft gloss border |
| **Navigation** | Standard fixed sidebar | Compact vertical capsule navigation rail (`.sidebar-rail`) with icon buttons + hover tooltips |
| **Typography** | Inconsistent text sizing (some 9px–11px) | Standardized Inter scale: Title 28–32px, Section 20–24px, Card Title 16–18px, Body 15–16px, Min 13px |
| **Spacing** | Arbitrary margins (13px, 19px, 27px) | Standard 8-point grid: `4, 8, 12, 16, 20, 24, 32, 40` |
| **Vertical Switcher** | Basic text tabs | Premium segmented glass control `[ 🪑 Мебель ] [ 🌾 Искусственный ротанг ]` with accent color shifting |
| **Global Search** | Standard input field | Command Palette modal (`Ctrl+K` / `Cmd+K`) for leads, competitors, and actions |
| **AI Assistant** | Static inline block | Floating openable glass drawer panel (`#gpt-drawer`) with quick prompt buttons |

---

## 4. Design System Tokens & Glass Classes

### 4.1 CSS Design Tokens
```css
:root {
  /* Backgrounds & Ambient Overlay */
  --bg-ambient-overlay: rgba(22, 26, 35, 0.45);
  --bg-glass-panel: rgba(30, 36, 48, 0.52);
  --bg-glass-card: rgba(255, 255, 255, 0.12);
  --bg-glass-card-hover: rgba(255, 255, 255, 0.20);
  
  /* Borders & Shadows */
  --glass-border: 1px solid rgba(255, 255, 255, 0.25);
  --glass-border-subtle: 1px solid rgba(255, 255, 255, 0.14);
  --glass-shadow: 0 30px 90px rgba(0, 0, 0, 0.40);
  
  /* Typography Scale */
  --font-size-title: 30px;
  --font-size-section: 22px;
  --font-size-card-title: 17px;
  --font-size-body: 15px;
  --font-size-table: 14px;
  --font-size-secondary: 13px;
  
  /* Spacing Tokens */
  --space-4: 4px;
  --space-8: 8px;
  --space-12: 12px;
  --space-16: 16px;
  --space-20: 20px;
  --space-24: 24px;
  --space-32: 32px;
  --space-40: 40px;
  
  /* Radius Tokens */
  --radius-sm: 10px;
  --radius-md: 16px;
  --radius-lg: 22px;
  --radius-shell: 36px;
  
  /* Vertical Accent Shifting */
  --accent-furniture: #f59e0b; /* Warm amber */
  --accent-rattan: #84cc16;    /* Natural olive/sand */
}
```

### 4.2 Reusable Glass Utility Classes
- `.glass-shell`: Floating main dashboard window over the ambient room backdrop.
- `.glass-panel`: Major section wrapper with `backdrop-filter: blur(40px)`.
- `.glass-card`: Primary widget container.
- `.glass-card-interactive`: Card with smooth hover elevation (`160ms ease`).
- `.glass-popover` / `.glass-modal`: Command palette modal (`Ctrl+K`).
- `#gpt-drawer`: Floating context-aware assistant drawer.

---

## 5. Execution Roadmap

1. **Step 1**: Write CSS design tokens & `.glass-*` utility classes in `app/web/static/app.css`.
2. **Step 2**: Update `base.html` shell, topbar, capsule navigation rail, vertical switcher, Command Palette (`Ctrl+K`), and GPT drawer.
3. **Step 3**: Update Jinja templates (`index.html`, `leads.html`, `lead_detail.html`, `audiences.html`, `competitors.html`, `openings.html`) to use `.glass-card`, `.glass-card-interactive`, and standard typography tokens.
4. **Step 4**: Update `app/web/static/app.js` with `Ctrl+K` command palette handler and GPT drawer toggle.
5. **Step 5**: Run full verification suite (`pytest`, `ruff`, `compileall`, and live readiness check).
