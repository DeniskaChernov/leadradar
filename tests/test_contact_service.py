from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Comment, Contact, ContactEvent, ContactEventType, Post
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.contact_service import ContactService


def make_post() -> InstagramPost:
    return InstagramPost(
        platform_post_id="post-1",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/post-1/",
        caption="6 kishilik stol",
        comments_count=1,
    )


def make_comment(comment_id: str = "comment-1") -> InstagramComment:
    return InstagramComment(
        platform_comment_id=comment_id,
        platform_user_id="user-1",
        username="Aziz_Test",
        display_name="Aziz",
        profile_url="https://www.instagram.com/aziz_test/",
        text="narxi?",
        created_at=datetime.now(UTC),
    )


async def test_contact_upsert_and_comment_deduplication(session_factory):
    service = ContactService(session_factory)
    first = await service.persist_signal(make_post(), make_comment())
    duplicate = await service.persist_signal(make_post(), make_comment())
    second_signal = await service.persist_signal(make_post(), make_comment("comment-2"))

    assert first.created is True
    assert duplicate.created is False
    assert second_signal.contact_id == first.contact_id

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(select(func.count(Comment.id))) == 2
        events = (
            await session.scalars(
                select(ContactEvent).where(
                    ContactEvent.event_type == ContactEventType.COMMENT_FOUND
                )
            )
        ).all()
        assert len(events) == 2


async def test_baseline_signal_is_persisted_without_losing_history(session_factory):
    result = await ContactService(session_factory).persist_signal(
        make_post(), make_comment(), is_baseline=True
    )

    async with session_factory() as session:
        comment = await session.get(Comment, result.comment_id)
        assert comment is not None
        assert comment.is_baseline is True
        assert await session.scalar(select(func.count(ContactEvent.id))) == 1


async def test_same_reel_url_from_another_provider_does_not_duplicate_post(
    session_factory,
):
    service = ContactService(session_factory)
    first = await service.persist_signal(make_post(), make_comment("comment-provider-a"))
    alternate_post = make_post().model_copy(update={"platform_post_id": "other-provider-id"})
    second = await service.persist_signal(
        alternate_post, make_comment("comment-provider-b")
    )

    assert first.post_id == second.post_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Post.id))) == 1
        assert await session.scalar(select(func.count(Comment.id))) == 2
