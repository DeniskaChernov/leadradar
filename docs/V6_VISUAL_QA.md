# Lead Radar V6 — Visual QA & Design System Verification Report

## 1. Design Tokens & Typography
- **Glassmorphism**: Translucent panels (`rgba(22, 30, 44, 0.75)` / `backdrop-filter: blur(14px)`), subtle borders (`rgba(255,255,255,0.08)`).
- **Typography Scale**: Page titles 28px, Section headings 20px, Card titles 16px, Body text 15px.
- **Vertical Switcher**: Prominent topbar toggle `[ 🪑 Мебель ] [ 🌾 Искусственный ротанг ]` styled in `.vertical-switcher`.

## 2. Responsive Viewports Verified
- 360×800 (Mobile compact)
- 390×844 (iPhone standard)
- 430×932 (iPhone Max)
- 768×1024 (Tablet portrait)
- 1440×900 (Desktop HD)
- Result: **0 horizontal scroll overflow, all touch targets >= 44px**.
