# Lead Radar V6 — UI & UX Audit Report

## 1. Current Web Interface Layout
- Built with FastAPI + Jinja2 SSR templates + CSS (`app/web/static/app.css`).
- Features navigation header, metrics grid, panel views, and responsive CSS containers.

## 2. Identified UI Issues & Enhancements Needed for V6

1. **Vertical Context Selector**: Missing prominent top navigation switch `[ Мебель ] [ Искусственный ротанг ]` to toggle vertical context across views.
2. **Design System Standardization**: Font sizes and card paddings vary slightly across pages. V6 standardizes design tokens (28-32px page titles, 20-24px section titles, 16-18px card titles, 15-16px body text).
3. **Openings Review Queue View**: `/openings` page needs a dedicated Jinja2 template layout to view and review pending venue opening signals (`VERIFIED` / `REJECTED`).
4. **Global Search Modal**: Needs keyboard-driven global search modal (`Ctrl+K` or search input) grouping results into People, Businesses, Signals, Leads, Audiences, and Catalog.
5. **OpenAI Agent Side Drawer**: Floating/expandable glass panel for context-aware assistant interaction on Lead, Audience, Competitor, and Rattan pages.
6. **Mobile Viewport Optimization**: Mini App viewports (360px, 390px, 430px) require touch targets >= 44px, safe area padding, and zero horizontal scrolling.
