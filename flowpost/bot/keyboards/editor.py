from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardMarkup

from flowpost.bot.callbacks import Ed
from flowpost.bot.keyboards.common import btn, chunked, markup, on, page_nav, paged
from flowpost.db.models import Channel, ChannelFolder, Post
from flowpost.i18n import t
from flowpost.services import ads, ideas
from flowpost.services.posts import AD_FORMATS, has_visual_media, options_of
from flowpost.services.rich import carousel_ready
from flowpost.services.slots import fmt_date, fmt_hm


# Editor buttons a user can hide in «Налаштування → Інтерфейс → Редактор постів»; the ones that only show up
# for a particular post (delete the caption or the source signature, media view, carousel…) aren't on the list.
EDITOR_TOGGLES = ["wm", "ai", "repeat", "multi", "idea"]


def _toggle_button(post: Post, key: str):
    p = post.id
    if key == "wm":
        return btn(on(options_of(post)["watermark"]) + t("ed.watermark"), Ed(a="wm", p=p))
    if key == "ai":
        return btn(t("ed.ai"), Ed(a="ai", p=p))
    if key == "repeat":
        return btn(on(bool(post.repeat and post.repeat.active)) + t("ed.repeat"), Ed(a="rep", p=p))
    if key == "multi":
        return btn(t("ed.multipost") + (f" ({len(post.targets)})" if len(post.targets) > 1 else ""), Ed(a="multi", p=p))
    return btn(t("ed.idea_keep") if ideas.is_idea(post) else t("ed.idea"), Ed(a="idea", p=p))


def _shown(post: Post, key: str, hidden) -> bool:
    """A hidden button still shows while its feature is on for this post, so it can always be switched off."""
    if key not in hidden:
        return True
    if key == "repeat":
        return bool(post.repeat and post.repeat.active)
    if key == "multi":
        return len(post.targets) > 1
    if key == "idea":
        return ideas.is_idea(post)
    return False


def hidden_buttons(post: Post, hidden, *, is_poll: bool = False) -> list:
    """The hidden editor buttons, for «Більше налаштувань»."""
    keys = [k for k in EDITOR_TOGGLES if not _shown(post, k, hidden)]
    if is_poll:
        keys = [k for k in keys if k not in ("wm", "ai")]
    if not ideas.can_keep(post):
        keys = [k for k in keys if k != "idea"]
    return [_toggle_button(post, k) for k in keys]


def ad_check_verdict(post: Post) -> str | None:
    """The verdict of the last «Перевірити рекламу», while the ad is still what was checked."""
    check = options_of(post)["ad_check"]
    return check["report"]["verdict"] if check and check.get("hash") == ads.content_hash(post) else None


def ad_kb(post: Post) -> InlineKeyboardMarkup:
    """«Налаштування реклами»: an ad's own settings instead of the regular editor."""
    p = post.id
    opts = options_of(post)
    booking = bool(opts["ad_booking"])
    hours = opts["auto_delete_hours"]
    rows = [
        [btn(t("ad.url_buttons"), Ed(a="btn", p=p)), btn(on(opts["link_preview"]) + t("ad.preview"), Ed(a="ad_t", p=p, v="link_preview"))],
        [btn(t("ad.reply_yes") if opts["reply_to"] else t("ad.reply_no"), Ed(a="ad_reply", p=p))],
        [
            btn(("🔘 " if opts["ad_format"] == n else "◯ ") + f"{top} / {feed}", Ed(a="ad_fmt", p=p, v=str(n)))
            for n, (top, feed) in AD_FORMATS.items()
        ],
        [
            btn(on(not opts["pin"]) + t("ad.no_pin"), Ed(a="ad_pin", p=p, v="0")),
            btn(t("ad.delete_hours", hours=hours) if hours else t("ad.delete_timer"), Ed(a="ad_del", p=p)),
        ],
        [
            btn(on(opts["pin"]) + t("ad.pin"), Ed(a="ad_pin", p=p, v="1")),
            btn(t("ad.silent") if opts["silent"] else t("ad.sound"), Ed(a="ad_t", p=p, v="silent")),
        ],
        [btn(("☑️ " if not opts["comments"] else "☐ ") + t("ad.no_comments"), Ed(a="ad_t", p=p, v="comments"))],
        [
            btn(t(f"adchk.btn_{verdict}") if (verdict := ad_check_verdict(post)) else t("adchk.btn"), Ed(a="ad_chk", p=p)),
            btn(("☑️ " if opts["ad_report"] else "☐ ") + t("adrep.btn"), Ed(a="ad_rep", p=p)),
        ],
        [
            btn(on(bool(post.repeat and post.repeat.active)) + t("ad.repeat"), Ed(a="rep", p=p)),
            btn(t("ad.multipost") + (f" ({len(post.targets)})" if len(post.targets) > 1 else ""), Ed(a="multi", p=p)),
        ],
    ]
    if booking:
        rows.append([btn(t("ad.schedule"), Ed(a="sch", p=p))])
        rows.append([btn(t("ad.confirm"), Ed(a="ad_ok", p=p))])
    else:
        rows.append([btn(t("ad.schedule"), Ed(a="sch", p=p)), btn(t("ad.publish"), Ed(a="pub", p=p))])
    rows.append([btn(t("ad.cancel"), Ed(a="cancel", p=p))])
    return markup(rows)


def editor_kb(post: Post, part_idx: int, *, published: bool, hidden=()) -> InlineKeyboardMarkup:
    if post.is_ad and not published:
        return ad_kb(post)
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

    def opt(key: str) -> list:
        return [_toggle_button(post, key)] if _shown(post, key, hidden) else []

    if published:
        if part.text_html.strip():
            rows.append([btn(t("ed.delete_text"), Ed(a="del_text", p=p))])
        if part.source_signature.strip():
            rows.append([btn(t("ed.delete_source_signature"), Ed(a="del_sig", p=p))])
        if is_poll:
            rows.append([btn(buttons_label, Ed(a="btn", p=p))])
        else:
            rows.append([btn(buttons_label, Ed(a="btn", p=p)), btn(media_label, Ed(a="media", p=p))])
            if opt("ai"):
                rows.append(opt("ai"))
        rows += [
            [btn(t("ed.save_published"), Ed(a="save", p=p))],
            [btn(t("ed.exit"), Ed(a="exit", p=p))],
        ]
        return markup(rows)

    if part.text_html.strip():
        rows.append([btn(t("ed.delete_text"), Ed(a="del_text", p=p))])
    if part.source_signature.strip():
        rows.append([btn(t("ed.delete_source_signature"), Ed(a="del_sig", p=p))])
    if is_poll:
        rows.append([btn(t("ed.delete_poll"), Ed(a="del_poll", p=p))])
        rows.append([btn(buttons_label, Ed(a="btn", p=p)), btn(t("ed.more"), Ed(a="more", p=p))])
    else:
        # hiding a button closes the gap: the rest of the grid moves up two to a row
        rows += chunked([
            *opt("wm"), btn(buttons_label, Ed(a="btn", p=p)),
            btn(media_label, Ed(a="media", p=p)), btn(on(opts["signature"]) + t("ed.signature"), Ed(a="sig", p=p)),
            *opt("ai"), btn(t("ed.more"), Ed(a="more", p=p)),
        ], 2)
        look = []
        if has_visual_media(part.media):
            look.append(btn(t("ed.media_view"), Ed(a="mview", p=p)))
        if carousel_ready(part.media) and not opts["paid"]:
            look.append(btn(on(opts["carousel"]) + t("ed.carousel"), Ed(a="carousel", p=p)))
        if look:
            rows.append(look)
    rows += chunked([
        btn(t("ed.messages") + (f" ({n})" if n > 1 else ""), Ed(a="parts", p=p)), *opt("repeat"),
        btn(t("ed.schedule"), Ed(a="sch", p=p)), *opt("multi"),
    ], 2)
    rows.append([btn(t("ed.publish"), Ed(a="pub", p=p))])
    cancel = btn(t("ed.cancel"), Ed(a="cancel", p=p))
    if ideas.can_keep(post):
        rows.append([*opt("idea"), cancel])
    else:
        rows.append([cancel])
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
    page: int = 0,
    per_page: int = 20,
) -> InlineKeyboardMarkup:
    from flowpost.bot.callbacks import Fd, Nc

    entries = [
        btn(t("fld.row", icon=f.icon, title=f.title, n=n), Fd(a="pick", f=f.id, p=post_id), f.style)
        for f, n in folders
    ]
    entries += [btn(("📢 " if c.kind == "channel" else "👥 ") + c.title, Nc(c=c.id, p=post_id)) for c in channels]
    page, pages = paged(page, len(entries), per_page)
    rows = [[e] for e in entries[page * per_page:(page + 1) * per_page]]
    if pages > 1:
        rows.append(page_nav(
            page, pages,
            lambda n: Fd(a="pick", f=folder_id, p=post_id, pg=n),
            Fd(a="noop", p=post_id),
        ))
    if folder_id:
        rows.append([btn(t("fld.leave"), Fd(a="pick", p=post_id))])
    return markup(rows)
