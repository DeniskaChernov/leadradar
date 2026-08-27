# Lead Radar V6 — Bot QA & Interaction Verification Report

## 1. Real-Time Notification Pipeline
1. Unique comment received from competitor -> Immediate alert `🔔 Новый сигнал` sent to Telegram outbox.
2. AI classification completes -> Outbox edits original message with score (`🔥 HOT 91/100`), factor breakdown, and quick action buttons.

## 2. Command Menu & WebApp Integration
- Bot commands: `/start`, `/status`, `/stats`, `/hot`, `/lead`, `/scan`, `/competitors`, `/web`, `/help`, `/cancel`.
- Deep links open exact web app entity views (`/leads/123`, `/openings`).
