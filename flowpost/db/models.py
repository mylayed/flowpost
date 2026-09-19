from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    balance: Mapped[int] = mapped_column(Integer, default=0)  # Stars
    cashback: Mapped[int] = mapped_column(Integer, default=0)  # Stars
    channels_per_page: Mapped[int] = mapped_column(Integer, default=20)
    channel_order: Mapped[list] = mapped_column(JSONType, default=list)  # channel ids pinned to the front
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SupportThread(Base):
    """A user's topic in the support group: their messages land there and the team's replies go back to them."""

    __tablename__ = "support_threads"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_support_threads_chat_user"),
        Index("ix_support_threads_chat_topic", "chat_id", "topic_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    topic_id: Mapped[int] = mapped_column(Integer)
    last_user_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # the user's latest message
    last_reply_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # the team's latest delivered reply
    awaiting: Mapped[bool] = mapped_column(Boolean, default=False)  # the user wrote last, nobody has answered yet
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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
    moderation: Mapped[dict] = mapped_column(JSONType, default=dict)
    # «Зберегти форматування та налаштування»: {"options": {...}, "buttons": [[{"text","url"}]]}
    post_defaults: Mapped[dict] = mapped_column(JSONType, default=dict)
    trial_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Join requests: {"approve": "off"|"now"|"<minutes>", "welcome": bool, "welcome_html": str, "link": str}
    join_settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Multiposted posts are translated into this language (uk, en, ...) for this channel; None = as written.
    translate_lang: Mapped[str | None] = mapped_column(String(8))
    weekly_report: Mapped[bool] = mapped_column(Boolean, default=True)
    report_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InviteLink(Base):
    """A tracked invite link, e.g. one per ad campaign: who joined through it and what it cost."""

    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(128), index=True)
    cost: Mapped[float | None] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InviteJoin(Base):
    """Someone who joined through a tracked link; `left_at` is set if they later left."""

    __tablename__ = "invite_joins"
    __table_args__ = (UniqueConstraint("link_id", "user_tg_id", name="uq_invite_joins_link_user"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("invite_links.id", ondelete="CASCADE"), index=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class JoinRequest(Base):
    """A request to join a channel the bot approves on the owner's behalf, right away or after a delay."""

    __tablename__ = "join_requests"
    __table_args__ = (UniqueConstraint("channel_id", "user_tg_id", name="uq_join_requests_channel_user"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger)
    invite_url: Mapped[str | None] = mapped_column(String(128))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    approve_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Feed(Base):
    """An RSS/Atom source whose new items become posts in a channel (drafts to review, or published right away)."""

    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(256), default="")
    mode: Mapped[str] = mapped_column(String(8), default="draft")  # draft | auto
    rewrite: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    seen: Mapped[list] = mapped_column(JSONType, default=list)  # ids of the latest items already handled
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MemberCount(Base):
    """A channel's subscriber count, one reading per day, for growth in the weekly report."""

    __tablename__ = "channel_member_counts"
    __table_args__ = (UniqueConstraint("channel_id", "day", name="uq_channel_member_counts_channel_day"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer)


class ChannelFolder(Base):
    """A user-defined group of channels used to narrow the channel pickers."""

    __tablename__ = "channel_folders"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(16), default="🗂")
    style: Mapped[str | None] = mapped_column(String(16))  # primary | success | danger; None = default look
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChannelFolderItem(Base):
    __tablename__ = "channel_folder_items"
    __table_args__ = (UniqueConstraint("folder_id", "channel_id", name="uq_channel_folder_items_folder_channel"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("channel_folders.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)


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
    poll: Mapped[dict | None] = mapped_column(JSONType, nullable=True, default=None)

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
    reactions: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"<message_id>": {"emoji": count}}
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    discussion_thread_id: Mapped[int | None] = mapped_column(Integer)
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


class BalanceEntry(Base):
    """Append-only wallet movement; User.balance / User.cashback are the running totals of these rows."""

    __tablename__ = "balance_ledger"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bucket: Mapped[str] = mapped_column(String(16))  # main | cashback
    delta: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # topup | cashback | spend | refund | admin
    ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChannelSubscription(Base):
    """Paid posting plan of one channel; can be moved to another channel of the same owner."""

    __tablename__ = "channel_subscriptions"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_channel_subscriptions_channel_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    posts_per_day: Mapped[int] = mapped_column(Integer)
    paid_until: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ChannelQuota(Base):
    """Extra usage bought for a channel on top of its plan (watermarks, AI texts)."""

    __tablename__ = "channel_quotas"
    __table_args__ = (UniqueConstraint("channel_id", "kind", name="uq_channel_quotas_channel_kind"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # wm_photo | wm_video | ai_text
    remaining: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


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


class Broadcast(Base):
    """The bot owner's message to many users at once (/broadcast): copied from `from_chat_id`/`message_id` to
    everyone in `audience`, now or at `send_at`. Recipients go in user id order and `last_user_id` marks progress,
    so a broadcast interrupted by a restart picks up where it stopped."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(BigInteger)  # the admin's Telegram id; reports go there
    from_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    audience: Mapped[str] = mapped_column(String(16))  # owners | channels | nochannels | all
    send_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | sending | done | cancelled
    status_message_id: Mapped[int | None] = mapped_column(Integer)  # the admin's progress message
    # rows of {"text", "url"} link buttons; {"add_channel": true} and {"manage_sub": true} are template buttons
    buttons: Mapped[list] = mapped_column(JSONType, default=list)
    last_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
