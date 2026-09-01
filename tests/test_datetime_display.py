from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.web.datetime_display import format_display_dt, parse_display_dt


def test_format_display_dt_converts_utc_to_tashkent():
    utc = datetime(2026, 9, 1, 5, 42, tzinfo=UTC)
    assert format_display_dt(utc, timezone="Asia/Tashkent") == "01.09 10:42"


def test_format_display_dt_handles_naive_as_utc():
    naive = datetime(2026, 9, 1, 5, 42)
    assert format_display_dt(naive, timezone="Asia/Tashkent") == "01.09 10:42"


def test_parse_display_dt_interprets_naive_as_local_then_utc():
    parsed = parse_display_dt("2026-09-01T10:42", timezone="Asia/Tashkent")
    assert parsed == datetime(2026, 9, 1, 5, 42, tzinfo=UTC)


def test_parse_display_dt_roundtrip_with_format_display_dt():
    utc = datetime(2026, 9, 1, 5, 42, tzinfo=UTC)
    shown = format_display_dt(utc, "%Y-%m-%dT%H:%M", timezone="Asia/Tashkent")
    parsed = parse_display_dt(shown, timezone="Asia/Tashkent")
    assert parsed == utc


def test_settings_reject_unknown_web_display_timezone():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, web_display_timezone="Asia/Tashkentt")
