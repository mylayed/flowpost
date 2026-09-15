from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .types import BigIntPK, JSONType, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    lang: Mapped[str] = mapped_column(String(8), default="uk")
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Kyiv")
    trial_ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    trial_reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Channel(Base):
    """A connected channel or group ("project")."""

    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("owner_id", "chat_id", name="uq_channels_owner_chat"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # channel | group
    title: Mapped[str] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64))
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    signature_template: Mapped[str | None] = mapped_column(Text)
    signature_on: Mapped[bool] = mapped_column(Boolean, default=True)
    watermark: Mapped[dict] = mapped_column(JSONType, default=dict)
    ai_style_prompt: Mapped[str | None] = mapped_column(Text)
    notify_published: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_recipients: Mapped[str] = mapped_column(String(16), default="owner")  # owner | admin | both
    discussion_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    discussion_title: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|scheduled|published|failed|cancelled
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    parts: Mapped[list[PostPart]] = relationship(
        back_populates="post", order_by="PostPart.position", cascade="all, delete-orphan", lazy="selectin"
    )
    targets: Mapped[list[PostTarget]] = relationship(
        cascade="all, delete-orphan", order_by="PostTarget.position", lazy="selectin"
    )
    repeat: Mapped[RepeatRule | None] = relationship(cascade="all, delete-orphan", uselist=False, lazy="selectin")

    @property
    def channel_ids(self) -> list[int]:
        return [t.channel_id for t in self.targets]


class PostPart(Base):
    """One message of a post; several parts form a series ("Повідомлення")."""

    __tablename__ = "post_parts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text_html: Mapped[str] = mapped_column(Text, default="")
    source_signature: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list] = mapped_column(JSONType, default=list)
    buttons: Mapped[list] = mapped_column(JSONType, default=list)

    post: Mapped[Post] = relationship(back_populates="parts")


class PostTarget(Base):
    __tablename__ = "post_targets"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class RepeatRule(Base):
    __tablename__ = "repeat_rules"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True)
    interval_minutes: Mapped[int] = mapped_column(Integer)
    remaining_count: Mapped[int | None] = mapped_column(Integer)
    until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Publication(Base):
    """A queued/finished delivery of a post into one channel."""

    __tablename__ = "publications"
    __table_args__ = (Index("ix_publications_status_run_at", "status", "run_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # pending|publishing|published|failed|cancelled|missed|paused
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    message_ids: Mapped[dict] = mapped_column(JSONType, default=dict)
    repeat_index: Mapped[int] = mapped_column(Integer, default=0)  # 0 = original, 1.. = auto-repeats
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delete_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    unpin_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(16))  # liqpay | manual (legacy rows may say "stars")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | cancelled | expired
    current_period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    renewal_reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_sub_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8))
    provider_payment_id: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    raw: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_user_kind_created", "user_id", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChannelAdmin(Base):
    """Delegated access: `user_id` may act on `channel_id` on the owner's behalf, within these permissions."""

    __tablename__ = "channel_admins"
    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_channel_admins_channel_user"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    can_settings: Mapped[bool] = mapped_column(Boolean, default=False)
    can_disconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChannelInvite(Base):
    """A one-time invite link an owner generates to grant someone ChannelAdmin access."""

    __tablename__ = "channel_invites"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    can_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    can_settings: Mapped[bool] = mapped_column(Boolean, default=False)
    can_disconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
