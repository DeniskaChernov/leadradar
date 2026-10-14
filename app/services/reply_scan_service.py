"""Explicit, budgeted public-thread collection with durable request and page checkpoints."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import Comment, Competitor, Post, ReplyScanRequest, ReplyThreadState
from app.providers.base import InstagramProvider, ProviderUsageBlockedError
from app.providers.public_data import ensure_public_source
from app.schemas.instagram import InstagramComment, InstagramPost


class ReplyScanConflict(ValueError):
    pass


class ReplyScanService:
    MAX_CREDITS = 20

    def __init__(self, session_factory, provider: InstagramProvider) -> None:
        self.session_factory = session_factory
        self.provider = provider

    async def target(self, comment_id: int, *, require_active: bool = True) -> tuple[Comment, InstagramPost]:
        if not self.provider.supports_comment_replies:
            raise ValueError("Текущий провайдер не поддерживает ответы в ветках")
        async with self.session_factory() as session:
            row = (await session.execute(
                select(Comment, Post, Competitor).join(Post, Post.id == Comment.post_id)
                .join(Competitor, Competitor.id == Comment.competitor_id)
                .where(Comment.id == comment_id),
            )).first()
        if row is None:
            raise LookupError("Комментарий не найден")
        comment, post, source = row
        if comment.parent_platform_comment_id:
            raise ValueError("Выберите основной комментарий, которому принадлежит ветка")
        if require_active and not source.active:
            raise ValueError("Источник приостановлен. Включите его перед проверкой ответов")
        ensure_public_source(post.raw_data)
        return comment, InstagramPost(
            platform_post_id=post.platform_post_id, competitor=source.normalized_handle,
            url=post.url, caption=post.caption or "", post_type=post.post_type,
            published_at=post.published_at, comments_count=post.comments_count,
            raw_data=post.raw_data or {},
        )

    async def preview(self, comment_id: int) -> dict:
        comment, post = await self.target(comment_id, require_active=False)
        async with self.session_factory() as session:
            state = await session.get(ReplyThreadState, comment_id)
            source = await session.get(Competitor, comment.competitor_id)
            count = int(await session.scalar(select(func.count(Comment.id)).where(
                Comment.post_id == comment.post_id,
                Comment.parent_platform_comment_id == comment.platform_comment_id,
            )) or 0)
        compatible = state and state.provider == self.provider.reply_cursor_provider
        return {
            "comment_id": comment_id, "post_id": comment.post_id,
            "vertical": source.vertical.value,
            "source_active": source.active,
            "source": post.competitor, "text": comment.text[:300], "saved_replies": count,
            "coverage": state.coverage_status if compatible else "UNKNOWN",
            "checked_at": state.checked_at.isoformat() if compatible and state.checked_at else None,
            "has_continuation": bool(compatible and state.next_cursor),
            "last_error": state.last_error if compatible else None,
            "maximum_credits": self.MAX_CREDITS,
        }

    async def existing(self, key: str) -> ReplyScanRequest | None:
        async with self.session_factory() as session:
            return await session.scalar(select(ReplyScanRequest).where(
                ReplyScanRequest.request_key == key,
            ))

    async def accept(self, key: str, comment_id: int, manager_id: int, max_credits: int):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ValueError("Нужен корректный Idempotency-Key")
        if not 1 <= max_credits <= self.MAX_CREDITS:
            raise ValueError(f"Лимит ответов должен быть от 1 до {self.MAX_CREDITS}")
        existing = await self.existing(key)
        if existing:
            if (existing.comment_id, existing.manager_id, existing.max_credits) != (
                comment_id, manager_id, max_credits,
            ):
                raise ReplyScanConflict("Этот ключ уже принадлежит другому запросу")
            return existing, False
        await self.target(comment_id)
        async with self.session_factory() as session:
            row = ReplyScanRequest(
                request_key=key, comment_id=comment_id, manager_id=manager_id,
                max_credits=max_credits, status="ACCEPTED",
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await self.accept(key, comment_id, manager_id, max_credits)
            return row, True

    async def scan(
        self, request_id: int,
        ingest: Callable[[InstagramPost, list[InstagramComment]], Awaitable[dict]],
    ) -> dict:
        async with self.session_factory() as session:
            request = await session.get(ReplyScanRequest, request_id)
            if request is None:
                raise LookupError("Запрос проверки не найден")
            if request.status != "ACCEPTED":
                return request.result or {}
            claimed = await session.execute(update(ReplyScanRequest).where(
                ReplyScanRequest.id == request_id, ReplyScanRequest.status == "ACCEPTED",
            ).values(status="RUNNING"))
            await session.commit()
            if claimed.rowcount != 1:
                return request.result or {}
        result = {"pages": 0, "comments_seen": 0, "comments_created": 0,
                  "leads_created": 0, "coverage": "UNKNOWN", "cached": False}
        error = None
        try:
            parent, post = await self.target(request.comment_id)
            async with self.session_factory() as session:
                state = await session.get(ReplyThreadState, parent.id)
            compatible = state and state.provider == self.provider.reply_cursor_provider
            checked = state.checked_at if compatible else None
            if checked and checked.tzinfo is None:
                checked = checked.replace(tzinfo=UTC)
            if compatible and state.coverage_status == "FULL" and checked and (
                datetime.now(UTC) - timedelta(hours=1) < checked <= datetime.now(UTC)
            ):
                result.update(coverage="FULL", cached=True)
            else:
                cursor = state.next_cursor if compatible else None
                visited = set(state.visited_cursors or []) if compatible and cursor else set()
                self.provider.begin_cycle()
                for _ in range(request.max_credits):
                    page = await self.provider.get_reply_batch(
                        post, parent.platform_comment_id, cursor=cursor,
                    )
                    error = page.fetch_error
                    if page.next_cursor and page.next_cursor in visited | {cursor}:
                        error = "RepeatedReplyCursor"
                    if not page.cursor_exhausted and not page.next_cursor and not error:
                        error = "UnconfirmedReplyPagination"
                    result["pages"] += page.pages_fetched
                    result["comments_seen"] += len(page.comments)
                    # Ingestion commits public signals/evidence/history before Telegram.
                    result.update(await ingest(post, page.comments))
                    if not error:
                        if cursor:
                            visited.add(cursor)
                        cursor = page.next_cursor
                    result["coverage"] = "FULL" if page.cursor_exhausted and not error else "PARTIAL"
                    async with self.session_factory() as session:
                        checkpoint = await session.get(ReplyThreadState, parent.id)
                        if checkpoint is None:
                            checkpoint = ReplyThreadState(comment_id=parent.id, pages_fetched=0)
                            session.add(checkpoint)
                        if checkpoint.provider != self.provider.reply_cursor_provider:
                            checkpoint.pages_fetched = 0
                        checkpoint.provider = self.provider.reply_cursor_provider
                        checkpoint.next_cursor = cursor
                        checkpoint.coverage_status = result["coverage"]
                        checkpoint.checked_at = datetime.now(UTC)
                        checkpoint.pages_fetched += page.pages_fetched
                        checkpoint.last_error = error
                        checkpoint.visited_cursors = sorted(visited)
                        saved_request = await session.get(ReplyScanRequest, request_id)
                        saved_request.result = dict(result)
                        await session.commit()
                    if error or page.cursor_exhausted:
                        break
        except asyncio.CancelledError:
            await asyncio.shield(self._finish(request_id, result, "InterruptedReplyScan"))
            raise
        except ProviderUsageBlockedError as exc:
            error = type(exc).__name__
        except Exception as exc:
            error = type(exc).__name__
        await self._finish(request_id, result, error)
        return {**result, "error": error}

    async def _finish(self, request_id: int, result: dict, error: str | None) -> None:
        async with self.session_factory() as session:
            row = await session.get(ReplyScanRequest, request_id)
            row.status = "FAILED" if error else "DONE"
            row.error = error
            row.result = dict(result)
            row.completed_at = datetime.now(UTC)
            await session.commit()
