# Lead Radar V6 — Telegram Bot UX Audit Report

## 1. Current Telegram Bot Functionality
- Built with Aiogram 3 (`app/bot/handlers.py`, `app/main.py`).
- Supports `/start`, `/status`, `/stats`, `/hot`, `/lead`, `/scan`, `/competitors`, `/web`, `/help`, `/cancel`.
- Inline callbacks for taking leads, assigning managers, viewing lead context.

## 2. Identified Bot UX Improvements Needed for V6

1. **Immediate Notification Lifecycle**:
   - Current: Waits for AI classification to complete before sending notification.
   - V6 Requirement: Sends immediate alert (`🔔 Новый сигнал`) upon receiving a new comment, then asynchronously edits the message (`🔥 HOT 91/100`) after AI analysis completes.
2. **Conversational Agent Mode**:
   - Allow manager to ask free-form questions to the AI Agent directly in Telegram chat (e.g., "Why is @user HOT?", "What offer should we recommend?").
3. **Configurable Digests**:
   - Scheduled morning brief, midday highlights, and end-of-day summary summarizing new HOT leads, B2B openings, and rattan discoveries.
4. **Deep Linking**:
   - WebApp buttons open exact entity detail pages (`/leads/123`, `/openings/45`).
