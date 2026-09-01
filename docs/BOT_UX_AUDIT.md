# Telegram Bot & Mini App UX Audit

## CURRENT BEHAVIOR
- Telegram bot handles incoming webhook commands and sends outbox notifications.
- Notifications support in-place message edits (`notify_analyzed_lead`) once analysis completes.
- Message edits use a durable in-progress content version plus an event-loop-scoped lock held
  through the Telegram edit and DB finalize; concurrent notifier instances cannot both edit.
- Basic callback queries allow triage actions (e.g. "Взять в работу", "Не лид").
- Daily morning/evening digests and quick task summaries were not yet fully automated.

## EXPECTED BEHAVIOR
- Telegram is treated as a first-class operational interface.
- Real-time signal alert workflow:
  1. Instant notification: `🔔 Новый сигнал` with comment preview, source handle, and `⏳ Анализируется` status.
  2. Automatic in-place edit: Upon completion of rule or AI analysis, message edits in place with score badge, intent, and action buttons (`[ Открыть карточку ]`, `[ Взять в работу ]`, `[ Не лид ]`).
- Interactive Keyboards: Direct one-tap status transitions without leaving Telegram.
- Configurable Automated Digests:
  - Morning Digest (09:00): HOT leads pending, new B2B inquiries, overdue tasks, top recommendation.
  - Evening Digest (19:00): Daily progress, conversions won, pipeline velocity.
- Deep Links: Direct seamless transitions into Web Mini App with pre-loaded lead context.

## BUGS
1. Missing scheduled morning/evening digest command handlers and cron dispatches.

## DATA RISKS
- Duplicate Telegram messages spamming operators if outbox idempotency is breached.

## COST RISKS
- Low.

## FALSE POSITIVE RISKS
- Low.

## FALSE NEGATIVE RISKS
- Operators missing high-priority leads if digests and real-time alerts fail to deliver.

## PROPOSED FIX
1. Implement `TelegramDigestService` generating rich morning/evening summaries.
2. Enhance inline keyboard callbacks for immediate triage.

## TESTS REQUIRED
- `test_telegram_message_edit_atomic_claim`
- `test_telegram_digest_generation`
- `test_telegram_callback_triage_actions`

The atomic edit claim is implemented and passed six consecutive concurrency stress runs. No
Telegram API call was made during verification.
