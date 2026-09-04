from app.config import Settings
from scripts.live_readiness_check import LocalReadinessState, evaluate_readiness


def _healthy_state(**changes) -> LocalReadinessState:
    values = {
        "database_healthy": True,
        "database_error": None,
        "migration_at_head": True,
        "migration_drift_free": True,
        "migration_error": None,
        "backup_present": True,
        "uncertain_reservations": 0,
    }
    values.update(changes)
    return LocalReadinessState(**values)


def _live_settings(**changes) -> Settings:
    values = {
        "external_kill_switch": False,
        "external_live_unlock": "ALLOW_EXTERNAL_CALLS",
        "instagram_live_calls_enabled": True,
        "instagram_provider": "scrapecreators",
        "scrapecreators_api_key": "configured-for-test",
        "ai_mode": "rules",
        "telegram_bot_token": "configured-for-test",
        "telegram_admin_chat_ids": [1001],
        "telegram_manager_chat_ids": [1001],
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_live_readiness_is_fail_closed_for_every_required_boundary():
    report = evaluate_readiness(_live_settings(), _healthy_state())
    assert report.offline_ready is True
    assert report.live_ready is True

    scenarios = [
        (_live_settings(external_kill_switch=True), _healthy_state(), "unlock"),
        (
            _live_settings(instagram_live_calls_enabled=False),
            _healthy_state(),
            "live calls",
        ),
        (_live_settings(instagram_provider="replay"), _healthy_state(), "live provider"),
        (_live_settings(scrapecreators_api_key=""), _healthy_state(), "API_KEY"),
        (_live_settings(telegram_bot_token=""), _healthy_state(), "TELEGRAM_BOT_TOKEN"),
        (_live_settings(telegram_admin_chat_ids=[]), _healthy_state(), "admin ID"),
        (
            _live_settings(telegram_manager_chat_ids=[]),
            _healthy_state(),
            "TELEGRAM_MANAGER_CHAT_IDS",
        ),
        (_live_settings(), _healthy_state(backup_present=False), "backup"),
        (
            _live_settings(),
            _healthy_state(uncertain_reservations=2),
            "UNCERTAIN",
        ),
    ]
    for settings, state, expected in scenarios:
        blocked = evaluate_readiness(settings, state)
        assert blocked.live_ready is False
        assert expected.lower() in " ".join(blocked.live_blocks).lower()


def test_database_or_migration_failure_blocks_offline_and_live_readiness():
    for state in (
        _healthy_state(database_healthy=False, database_error="connection failed"),
        _healthy_state(migration_at_head=False, migration_error="current=old"),
        _healthy_state(migration_drift_free=False, migration_error="new upgrade ops"),
    ):
        report = evaluate_readiness(_live_settings(), state)
        assert report.offline_ready is False
        assert report.live_ready is False
        assert report.offline_blocks
