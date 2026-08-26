from app.bot.handlers.router import LOST_REASONS, lost_reason_keyboard, main_menu
from app.main import _register_bot_commands


def test_main_menu_exposes_primary_commands():
    labels = {
        button.text
        for row in main_menu().keyboard
        for button in row
    }

    assert {"/status", "/stats", "/hot", "/scan", "/competitors", "/help"} <= labels


def test_lost_reason_keyboard_has_safe_unique_callbacks():
    markup = lost_reason_keyboard(123)
    callback_values = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert len(callback_values) == len(LOST_REASONS) + 1
    assert len(callback_values) == len(set(callback_values))
    assert all(value is not None and len(value) <= 64 for value in callback_values)


async def test_telegram_command_menu_contains_operational_commands():
    class BotStub:
        def __init__(self):
            self.commands = []

        async def set_my_commands(self, commands):
            self.commands = commands

    bot = BotStub()
    await _register_bot_commands(bot)  # type: ignore[arg-type]

    names = {item.command for item in bot.commands}
    assert {"status", "stats", "hot", "lead", "scan", "help", "cancel"} <= names
