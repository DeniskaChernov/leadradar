from __future__ import annotations

import sys

import pytest

from app import main as main_module


def test_main_treats_keyboard_interrupt_as_clean_shutdown(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["lead-radar"])

    def interrupt(_awaitable):
        _awaitable.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module.asyncio, "run", interrupt)

    with pytest.raises(SystemExit) as stopped:
        main_module.main()

    assert stopped.value.code == 0
