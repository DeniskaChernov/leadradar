import logging
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.db.models import Lead, LeadStatus
from app.main import configure_logging, init_error_monitoring
from app.schemas.leads import Intent, LeadAnalysis
from app.services.ai_service import HybridLeadAnalyzer, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post


class PlusOpenAIMock:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze(self, context):
        self.calls.append(context.comment)
        return LeadAnalysis(
            is_lead=True,
            lead_score=82,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            language="ru",
            reason="Плюс под CTA с ценами — коммерческий интерес",
        )


async def test_plus_comment_routes_to_openai_via_hybrid_analyzer(session_factory):
    mock = PlusOpenAIMock()
    hybrid = HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), mock, mode="hybrid")
    post = make_post().model_copy(
        update={"caption": "Оставьте плюс, чтобы получить каталог и цены"}
    )
    comment = make_comment("plus-regression").model_copy(update={"text": "+"})
    signal = await ContactService(session_factory).persist_signal(post, comment)
    result = await LeadService(session_factory, hybrid, hot_threshold=70).process_signal(signal)

    assert result is not None
    assert mock.calls == ["+"]
    assert result.status == LeadStatus.NEW
    async with session_factory() as session:
        lead = await session.scalar(select(Lead).where(Lead.comment_id == signal.comment_id))
    assert lead is not None
    assert lead.ai_source == "openai_or_cache"


def test_design_tokens_doc_in_app_css():
    css = Path("app/web/static/app.css").read_text(encoding="utf-8")
    assert "Lead Radar design tokens (D20)" in css
    assert "--brand:" in css
    assert "--motion-fast:" in css


def test_backup_runbook_has_restore_drill():
    text = Path("docs/BACKUP_RESTORE_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Restore Drill" in text
    assert "check_data_integrity" in text


def test_postgresql_migration_checklist_exists():
    path = Path("docs/POSTGRESQL_MIGRATION_CHECKLIST.md")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "postgresql+asyncpg" in text
    assert "GET /ready" in text


def test_railway_doc_exists():
    text = Path("docs/RAILWAY.md").read_text(encoding="utf-8")
    assert "railway.json" in text
    assert "healthcheckPath" in text
    assert "DOCKERFILE" in text


def test_pull_request_template_mentions_bugbot():
    text = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
    assert "Bugbot" in text


def test_configure_logging_json_format(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging(Settings(_env_file=None, log_level="INFO"))
    root = logging.getLogger()
    assert root.handlers
    assert '"level"' in root.handlers[0].formatter._fmt


def test_init_error_monitoring_noop_without_dsn():
    init_error_monitoring(Settings(_env_file=None, sentry_dsn=""))


def test_init_error_monitoring_warns_when_sdk_missing(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentry_sdk":
            raise ImportError("no sentry")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    init_error_monitoring(Settings(_env_file=None, sentry_dsn="https://example@sentry.io/1"))
    assert any("sentry_sdk_missing" in record.message for record in caplog.records)
