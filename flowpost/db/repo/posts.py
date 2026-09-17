from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flowpost.db.models import Post, PostPart, PostTarget
from flowpost.db.repo import channel_admins as channel_admins_repo


async def create_post(
    session: AsyncSession,
    owner_id: int,
    channel_ids: list[int],
    *,
    is_ad: bool = False,
    options: dict | None = None,
    text: str = "",
    media: list[dict] | None = None,
    source_signature: str = "",
    poll: dict | None = None,
    buttons: list | None = None,
) -> Post:
    post = Post(owner_id=owner_id, is_ad=is_ad, options=dict(options or {}), status="draft")
    post.parts = [PostPart(position=0, text_html=text or "", media=list(media or []), buttons=list(buttons or []),
                            source_signature=source_signature or "", poll=poll)]
    post.targets = [PostTarget(channel_id=cid, position=i) for i, cid in enumerate(channel_ids)]
    post.repeat = None
    session.add(post)
    await session.flush()
    return post


async def get_post(session: AsyncSession, owner_id: int, post_id: int) -> Post | None:
    stmt = (
        select(Post)
        .where(Post.id == post_id)
        .options(selectinload(Post.parts), selectinload(Post.targets), selectinload(Post.repeat))
        .execution_options(populate_existing=True)
    )
    post = await session.scalar(stmt)
    if post is None:
        return None
    if post.owner_id == owner_id:
        return post
    if not post.channel_ids:
        return None
    admin_ids = await channel_admins_repo.administered_channel_ids(session, owner_id, perm="posts")
    if all(cid in admin_ids for cid in post.channel_ids):
        return post
    return None


def set_targets(post: Post, channel_ids: list[int]) -> None:
    keep = {t.channel_id: t for t in post.targets}
    for target in list(post.targets):
        if target.channel_id not in channel_ids:
            post.targets.remove(target)
    for i, cid in enumerate(channel_ids):
        if cid in keep:
            keep[cid].position = i
        else:
            post.targets.append(PostTarget(post_id=post.id, channel_id=cid, position=i))


def add_part(post: Post) -> PostPart:
    part = PostPart(position=len(post.parts), text_html="", media=[], buttons=[])
    post.parts.append(part)
    return part


def remove_part(post: Post, index: int) -> None:
    if len(post.parts) <= 1 or not 0 <= index < len(post.parts):
        return
    post.parts.remove(post.parts[index])
    for i, part in enumerate(post.parts):
        part.position = i


async def recent_posts(
    session: AsyncSession, owner_id: int, statuses: tuple[str, ...], limit: int = 10, *,
    channel_ids: list[int] | None = None,
) -> list[Post]:
    stmt = select(Post).where(Post.owner_id == owner_id, Post.status.in_(statuses))
    if channel_ids:
        stmt = stmt.where(Post.id.in_(select(PostTarget.post_id).where(PostTarget.channel_id.in_(channel_ids))))
    stmt = stmt.order_by(Post.updated_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())
