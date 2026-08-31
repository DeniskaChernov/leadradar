from app.bot.handlers.router import LOST_REASONS, build_main_menu, lost_reason_keyboard
from app.config import Settings
from app.main import _register_bot_commands


def test_main_menu_exposes_primary_commands():
    labels = {
        button.text
        for row in build_main_menu(Settings(_env_file=None)).keyboard
        for button in row
    }

    assert {"/status", "/stats", "/hot", "/scan", "/competitors", "/help"} <= labels


def test_main_menu_adds_webapp_button_for_https_public_url():
    menu = build_main_menu(
        Settings(
            _env_file=None,
            web_host="0.0.0.0",
            web_public_url="https://lead-radar.example",
            web_auth_enabled=True,
            telegram_bot_token="test-token",
            telegram_admin_chat_ids=[101],
        )
    )
    webapp_buttons = [
        button
        for row in menu.keyboard
        for button in row
        if button.web_app is not None
    ]
    assert len(webapp_buttons) == 1
    assert webapp_buttons[0].text == "🌐 Кабина"
    assert webapp_buttons[0].web_app.url == "https://lead-radar.example"


def test_main_menu_keeps_web_command_without_https_url():
    menu = build_main_menu(Settings(_env_file=None, web_host="127.0.0.1", web_port=8000))
    labels = {button.text for row in menu.keyboard for button in row}
    assert "/web" in labels


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
