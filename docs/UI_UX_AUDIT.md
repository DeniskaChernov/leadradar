# UI/UX & Design System Audit

## CURRENT BEHAVIOR
- Web interface uses custom CSS with frosted glass styling and responsive tables.
- Recent polish resolved raw empty states and restored card styling.
- Typography scale and component tokens were partially decentralized across different CSS class rules.
- Mobile viewports (375px, 390px, 430px) occasionally had dense action strips or tight padding.
- Feature maturity status was not explicitly indicated on all experimental pages.

## EXPECTED BEHAVIOR
- Unified Design System Tokens:
  - Strict CSS variables for color palettes, frosted glass opacities, backdrop blurs, corner radii (16–24px), shadows, and motion timings (120–320ms, no bouncy easing).
- Strict Typography Scale:
  - Page titles: 28–32px, Section titles: 20–24px, Card titles: 16–18px, Body: 15–16px, Table text: 14–15px, Minimum secondary labels: >= 13px (zero unreadable 9–11px text).
- Action-Oriented Dashboard:
  - Top cards focus exclusively on actionable items: Urgent Attention, HOT Leads, B2B Opportunities, Rattan Signals, Openings, and Spend Health.
- Full Mobile Optimization:
  - Flawless ergonomics at 375px, 390px, and 430px with minimum 44px touch targets and dynamic safe areas.
- Truthful Feature Badges:
  - Explicit badges for `LIVE`, `OFFLINE`, `PROTOTYPE`, `MOCK`, `NOT_CONNECTED`.

## BUGS
1. Hardcoded font sizes in certain small badges violated the 13px minimum legibility rule.
2. Prototype integrations (Meta Ads, Google Marketing) did not clearly disclose their offline/prototype status to the user.

## DATA RISKS
- None.

## COST RISKS
- None.

## FALSE POSITIVE RISKS
- Users misunderstanding prototype screens as live external data feeds.

## FALSE NEGATIVE RISKS
- None.

## PROPOSED FIX
1. Centralize design tokens in `app.css` (`:root` variables).
2. Audit all font-size declarations to enforce the >= 13px rule.
3. Add maturity badges to headers across all feature views.
4. Verify mobile ergonomics at 375px, 390px, and 430px.

## TESTS REQUIRED
- `test_web_theme_tokens_present`
- `test_typography_minimum_font_size`
- `test_feature_maturity_badges_displayed`
