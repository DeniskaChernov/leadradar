"""The initial free-hosting deployment must stay isolated from live workflows."""

import json
from pathlib import Path


def test_initial_render_service_is_free_authenticated_and_cannot_run_live_work():
    config = json.loads((Path(__file__).resolve().parents[1] / "render.yaml").read_text())
    assert set(config) == {"services"}  # No paid disk/database/worker resources.
    assert len(config["services"]) == 1
    service = config["services"][0]
    assert service["plan"] == "free"
    assert service["autoDeployTrigger"] == "off"
    assert service["dockerCommand"] == "python -m app.main --web-only"
    assert service["healthCheckPath"] == "/health/runtime"
    values = {item["key"]: item.get("value") for item in service["envVars"]}
    assert values["WEB_AUTH_ENABLED"] == "true"
    assert values["EXTERNAL_KILL_SWITCH"] == "true"
    assert values["EXTERNAL_LIVE_UNLOCK"] == ""
    for key in ("INSTAGRAM_LIVE_CALLS_ENABLED", "OPENAI_LIVE_CALLS_ENABLED",
                "LEAD_SEARCH_ENABLED", "MONITOR_SCHEDULE_ENABLED", "AI_PENDING_RETRY_ENABLED"):
        assert values[key] == "false"
    assert values["INSTAGRAM_PROVIDER"] == "replay"
    assert "TELEGRAM_BOT_TOKEN" not in values
    secrets = {item["key"]: item for item in service["envVars"] if item.get("sync") is False}
    assert set(secrets) == {"DATABASE_URL", "WEB_PUBLIC_URL", "WEB_PASSWORD_HASH", "TELEGRAM_ADMIN_CHAT_IDS"}
    assert all("value" not in item for item in secrets.values())
    assert next(item for item in service["envVars"] if item["key"] == "WEB_SESSION_SECRET") == {
        "key": "WEB_SESSION_SECRET", "generateValue": True,
    }
