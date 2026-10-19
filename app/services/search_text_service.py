"""Unicode text matching for SQLite; registering a function never rewrites saved text."""

from sqlalchemy import event, func


def _casefold(value):
    return str(value).casefold() if value is not None else None


def _register_casefold(connection, record, _proxy):
    # Checkout also covers connections already opened before the query service
    # was created. Register once per DBAPI connection, not per query/session.
    if not record.info.get("leadradar_casefold"):
        connection.create_function("leadradar_casefold", 1, _casefold, deterministic=True)
        record.info["leadradar_casefold"] = True


def text_casefold(session_factory):
    engine = getattr(session_factory, "kw", {}).get("bind")
    if engine is not None and engine.dialect.name == "sqlite":
        if not event.contains(engine.sync_engine, "checkout", _register_casefold):
            event.listen(engine.sync_engine, "checkout", _register_casefold)
        return func.leadradar_casefold
    return func.lower
