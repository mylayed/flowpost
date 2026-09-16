from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardMarkup

from flowpost.bot.callbacks import Ed
from flowpost.bot.keyboards.common import btn, chunked, markup, on
from flowpost.db.models import Channel, ChannelFolder, Post
from flowpost.i18n import t
from flowpost.services.posts import options_of
from flowpost.services.slots import fmt_date, fmt_hm


def editor_kb(post: Post, part_idx: int, *, published: bool) -> InlineKeyboardMarkup:
    p = post.id
    opts = options_of(post)
    part = post.parts[part_idx]
    n = len(post.parts)
    is_poll = bool(part.poll)
    rows = []
    if n > 1:
        rows.append([
            btn("◀️", Ed(a="part", p=p, v=str(max(0, part_idx - 1)))),
            btn(t("ed.part_short", n=part_idx + 1, total=n), Ed(a="noop", p=p)),
            btn("▶️", Ed(a="part", p=p, v=str(min(n - 1, part_idx + 1)))),
        ])
    buttons_label = t("ed.buttons") + (f" ({sum(len(r) for r in part.buttons)})" if part.buttons else "")
    media_label = t("ed.media") + (f" ({len(part.media)})" if part.media else "")

    if published:
        if part.text_html.strip():
            rows.append([btn(t("ed.delete_text"), Ed(a="del_text", p=p))])
        if part.source_signature.strip():
            rows.append([btn(t("ed.delete_source_signature"), Ed(a="del_sig", p=p))])
        if is_poll:
            rows.append([btn(buttons_label, Ed(a="btn", p=p))])
        else:
            rows += [
                [btn(buttons_label, Ed(a="btn", p=p)), btn(media_label, Ed(a="media", p=p))],
                [btn(t("ed.ai"), Ed(a="ai", p=p))],
            ]
        rows += [
            [btn(t("ed.save_published"), Ed(a="save", p=p))],
            [btn(t("ed.exit"), Ed(a="exit", p=p))],
        ]
        return markup(rows)

    repeat_on = bool(post.repeat and post.repeat.active)
    multi_label = t("ed.multipost") + (f" ({len(post.targets)})" if len(post.targets) > 1 else "")
    if part.text_html.strip():
        rows.append([btn(t("ed.delete_text"), Ed(a="del_text", p=p))])
    if part.source_signature.strip():
        rows.append([btn(t("ed.delete_source_signature"), Ed(a="del_sig", p=p))])
    if is_poll:
        rows.append([btn(t("ed.delete_poll"), Ed(a="del_poll", p=p))])
        rows.append([btn(buttons_label, Ed(a="btn", p=p)), btn(t("ed.more"), Ed(a="more", p=p))])
    else:
        rows += [
            [btn(on(opts["watermark"]) + t("ed.watermark"), Ed(a="wm", p=p)), btn(buttons_label, Ed(a="btn", p=p))],
            [btn(media_label, Ed(a="media", p=p)), btn(on(opts["signature"]) + t("ed.signature"), Ed(a="sig", p=p))],
            [btn(t("ed.ai"), Ed(a="ai", p=p)), btn(t("ed.more"), Ed(a="more", p=p))],
        ]
    rows += [
        [btn(t("ed.messages") + (f" ({n})" if n > 1 else ""), Ed(a="parts", p=p)),
         btn(on(repeat_on) + t("ed.repeat"), Ed(a="rep", p=p))],
        [btn(t("ed.schedule"), Ed(a="sch", p=p)), btn(multi_label, Ed(a="multi", p=p))],
        [btn(t("ed.publish"), Ed(a="pub", p=p))],
        [btn(t("ed.cancel"), Ed(a="cancel", p=p))],
    ]
    return markup(rows)


def back_kb(post_id: int) -> InlineKeyboardMarkup:
    return markup([[btn(t("btn.back"), Ed(a="home", p=post_id))]])


def confirm_kb(post_id: int, yes_action: str, yes_label: str, value: str = "", back_action: str = "home") -> InlineKeyboardMarkup:
    return markup([
        [btn(yes_label, Ed(a=yes_action, p=post_id, v=value))],
        [btn(t("btn.back"), Ed(a=back_action, p=post_id))],
    ])


def schedule_kb(
    post_id: int,
    day: date,
    today: date,
    slots: list,
    has_more: bool,
    page: int,
    lang: str,
    busy: set[str],
    recommended: set[str] = frozenset(),
) -> InlineKeyboardMarkup:
    p = post_id
    ordinal = day.toordinal()
    # ":" is the CallbackData separator, so values use "_" between their own fields.
    nav = [
        btn("◀️", Ed(a="sch", p=p, v=f"{ordinal - 1}_0")) if day > today else btn("·", Ed(a="noop", p=p)),
        btn(fmt_date(day, lang), Ed(a="noop", p=p)),
        btn("▶️", Ed(a="sch", p=p, v=f"{ordinal + 1}_0")) if (day - today).days < 365 else btn("·", Ed(a="noop", p=p)),
    ]
    rows = [nav]

    def _mark(s) -> str:
        if fmt_hm(s) in busy:
            return "🔸"
        return "⭐" if fmt_hm(s) in recommended else ""

    slot_buttons = [
        btn(_mark(s) + fmt_hm(s), Ed(a="slot", p=p, v=f"{ordinal}_{s.hour:02d}{s.minute:02d}"))
        for s in slots
    ]
    rows += chunked(slot_buttons, 4)
    if has_more:
        rows.append([btn(t("sch.more_slots"), Ed(a="sch", p=p, v=f"{ordinal}_{page + 1}"))])
    rows.append([btn(t("btn.back"), Ed(a="home", p=p))])
    return markup(rows)


def channels_pick_kb(
    channels: list[Channel],
    post_id: int,
    folders: list[tuple[ChannelFolder, int]] = (),
    *,
    folder_id: int = 0,
) -> InlineKeyboardMarkup:
    from flowpost.bot.callbacks import Fd, Nc

    rows = [[btn(t("fld.row", title=f.title, n=n), Fd(a="pick", f=f.id, p=post_id))] for f, n in folders]
    rows += [[btn(("📢 " if c.kind == "channel" else "👥 ") + c.title, Nc(c=c.id, p=post_id))] for c in channels]
    if folder_id:
        rows.append([btn(t("fld.leave"), Fd(a="pick", p=post_id))])
    return markup(rows)
