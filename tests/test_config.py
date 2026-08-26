from app.config import Settings


def test_comma_separated_list_settings(monkeypatch):
    monkeypatch.setenv("COMPETITORS", "aiko.uz, @second_shop")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_IDS", "123456, -100987654")

    settings = Settings(_env_file=None)

    assert settings.competitors == ["aiko.uz", "second_shop"]
    assert settings.telegram_admin_chat_ids == [123456, -100987654]


def test_empty_list_settings_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("COMPETITORS", "")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_IDS", "")

    settings = Settings(_env_file=None)

    assert settings.competitors == ["aiko.uz"]
    assert settings.telegram_admin_chat_ids == []


def test_replay_is_a_valid_safe_provider():
    settings = Settings(_env_file=None, instagram_provider="replay")
    assert settings.instagram_provider == "replay"
    assert settings.instagram_live_calls_enabled is False
