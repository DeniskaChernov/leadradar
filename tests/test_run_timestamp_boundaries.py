from datetime import UTC, datetime, timedelta

from app.db.models import CostEvent, MonitorRun, MonitorRunStatus
from app.services import monitor_run_service as run_module
from app.services.monitor_run_service import MonitorRunService


async def _saved_run_and_credit(session_factory, *, run_started, event_created, event_key):
    async with session_factory() as session:
        run = MonitorRun(status=MonitorRunStatus.RUNNING, started_at=run_started)
        session.add(run)
        session.add(
            CostEvent(
                idempotency_key=event_key,
                service="instagram",
                provider="scrapecreators",
                operation="get_comment_page",
                units=1,
                created_at=event_created,
            )
        )
        await session.commit()
        return run.id


async def test_credit_committed_at_completion_timestamp_is_not_lost(
    file_session_factory,
    monkeypatch,
):
    finished = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return finished if tz else finished.replace(tzinfo=None)

    monkeypatch.setattr(run_module, "datetime", FrozenDateTime)
    run_id = await _saved_run_and_credit(
        file_session_factory,
        run_started=finished - timedelta(seconds=1),
        event_created=finished,
        event_key="committed-before-close-at-same-timestamp",
    )
    service = MonitorRunService(file_session_factory, "scrapecreators")
    await service.finish_failure(run_id, RuntimeError("cancelled"))
    async with file_session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        assert run.actual_credits_spent == 1
        assert run.operations_json == {"get_comment_page": 1}


async def test_credit_at_next_scan_start_is_excluded_from_prior_scan(file_session_factory):
    next_started = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    run_id = await _saved_run_and_credit(
        file_session_factory,
        run_started=next_started - timedelta(seconds=1),
        event_created=next_started,
        event_key="next-scan-first-credit",
    )
    async with file_session_factory() as session:
        session.add(MonitorRun(status=MonitorRunStatus.RUNNING, started_at=next_started))
        await session.commit()
    service = MonitorRunService(file_session_factory, "scrapecreators")
    await service.finish_failure(
        run_id,
        RuntimeError("recovered"),
        ended_at=next_started + timedelta(seconds=2),
    )
    async with file_session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        assert run.actual_credits_spent == 0
        assert run.operations_json == {}


async def test_equal_scan_start_times_do_not_assign_later_credit_twice(file_session_factory):
    started = datetime(2026, 10, 7, 5, 0, 0, tzinfo=UTC)
    prior_id = await _saved_run_and_credit(
        file_session_factory,
        run_started=started,
        event_created=started,
        event_key="credit-with-ambiguous-clock-timestamp",
    )
    async with file_session_factory() as session:
        later = MonitorRun(status=MonitorRunStatus.RUNNING, started_at=started)
        session.add(later)
        await session.commit()
        later_id = later.id
    service = MonitorRunService(file_session_factory, "scrapecreators")
    completed = started + timedelta(seconds=1)
    await service.finish_failure(prior_id, RuntimeError("recovered prior"), ended_at=completed)
    await service.finish_failure(later_id, RuntimeError("recovered later"), ended_at=completed)
    async with file_session_factory() as session:
        prior = await session.get(MonitorRun, prior_id)
        later = await session.get(MonitorRun, later_id)
        assert prior.actual_credits_spent == 0
        assert later.actual_credits_spent == 1
        assert later.operations_json == {"get_comment_page": 1}
