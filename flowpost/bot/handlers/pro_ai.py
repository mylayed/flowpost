"""PRO AI tools in «⭐ PRO-інструменти»: the channel's voice profile, an ad post from an advertiser's brief, niche
research among competitors and the AI answerer in comments. Like the other PRO tools they work while the channel is
on a paid plan or trial, for its owner and its admins with the settings right."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from flowpost.bot.callbacks import Px
from flowpost.bot.handlers.channel_settings import MAX_STYLE
from flowpost.bot.handlers.editor.view import open_editor
from flowpost.bot.handlers.pro import _back, _channel, _edit, _input_channel
from flowpost.bot.keyboards.common import btn, markup, on
from flowpost.bot.states import ProInput
from flowpost.config import Settings
from flowpost.db.models import Channel, User
from flowpost.db.repo import posts as posts_repo
from flowpost.i18n import t
from flowpost.services import analytics, pro_ai
from flowpost.services import ideas as ideas_service
from flowpost.services.ai import AIError, AIService
from flowpost.services.html_sanitize import snippet, visible_len
from flowpost.services.posts import TEXT_LIMIT, initial_options, render_signature
from flowpost.services.pro_ai import ProAIError
from flowpost.services.publisher import Publisher

router = Router(name="pro_ai")
PANEL_LIMIT = 3900
MAX_BRIEF = 3000


def _fit(text: str) -> str:
    return text if len(text) <= PANEL_LIMIT else text[:PANEL_LIMIT].rsplit("\n", 1)[0] + "\n…"


async def _run(
    session: AsyncSession, settings: Settings, user: User, channel: Channel, ai: AIService, action: str, call,
):
    """Spend one AI text of the channel, run `call()` and return its result; the text is refunded if it fails.
    Raises ProAIError with the i18n key to show."""
    if not ai.enabled:
        raise ProAIError("ai.disabled")
    await pro_ai.spend(session, settings, user, channel)
    try:
        result = await call()
    except AIError as e:
        await pro_ai.refund(session, channel.id)
        raise ProAIError(e.key) from e
    analytics.track(session, user.id, "ai_call", action=action)
    return result


# ---- 🎯 voice of the channel ------------------------------------------------------------------------------------

def voice_view(channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    current = html.escape(snippet(channel.ai_style_prompt, 700)) if channel.ai_style_prompt else t("ai.style_none")
    lines = [t("voice.title", title=html.escape(channel.title)), "", t("voice.help"), "", t("voice.current", style=current)]
    rows = [[btn(t("voice.go"), Px(a="voice_go", c=channel.id))], _back(channel)]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a == "voice"))
async def px_voice(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                   settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(None)
    await cb.answer()
    await _edit(cb, *voice_view(channel))


@router.callback_query(Px.filter(F.a == "voice_go"))
async def px_voice_go(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings, ai: AIService) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    texts = await pro_ai.top_texts(session, channel, pro_ai.VOICE_POSTS)
    if len(texts) < pro_ai.VOICE_MIN_POSTS:
        await cb.answer(t("voice.few_posts", n=pro_ai.VOICE_MIN_POSTS), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, t("voice.working", n=len(texts)), None)
    back = markup([_back(channel, "voice")])
    try:
        profile = await _run(session, settings, user, channel, ai, "voice", lambda: ai.voice_profile(
            texts, channel_title=channel.title, lang=user.lang,
        ))
    except ProAIError as e:
        await _edit(cb, t(e.key), back)
        return
    await state.update_data(voice_channel=channel.id, voice_profile=profile)
    text = t("voice.result", n=len(texts)) + f"\n\n<blockquote>{html.escape(profile)}</blockquote>\n\n" + t("voice.result_help")
    await _edit(cb, _fit(text), markup([
        [btn(t("voice.save"), Px(a="voice_ok", c=channel.id))],
        [btn(t("ai.again"), Px(a="voice_go", c=channel.id))],
        _back(channel, "voice"),
    ]))


@router.callback_query(Px.filter(F.a == "voice_ok"))
async def px_voice_save(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                        settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    data = await state.get_data()
    profile = data.get("voice_profile")
    if not profile or data.get("voice_channel") != channel.id:
        await cb.answer(t("voice.expired"), show_alert=True)
        return
    channel.ai_style_prompt = profile[:MAX_STYLE]
    await state.update_data(voice_profile=None)
    await session.flush()
    await cb.answer(t("voice.saved"), show_alert=True)
    await _edit(cb, *voice_view(channel))


# ---- 🤝 ad post from a brief ------------------------------------------------------------------------------------

def _ad_limit(channel: Channel) -> int:
    return TEXT_LIMIT - (visible_len(render_signature(channel)) + 2 if channel.signature_on else 0)


@router.callback_query(Px.filter(F.a == "adgen"))
async def px_ad(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(ProInput.ad_brief)
    await state.update_data(px_channel=channel.id)
    await cb.answer()
    await _edit(cb, t("adgen.prompt", title=html.escape(channel.title)), markup([_back(channel)]))


async def _ad_result(
    session: AsyncSession, settings: Settings, state: FSMContext, user: User, channel: Channel, ai: AIService, brief: str,
) -> tuple[str, InlineKeyboardMarkup]:
    back = markup([_back(channel)])
    try:
        text = await _run(session, settings, user, channel, ai, "ad", lambda: ai.generate(
            "ad", text=brief, lang=user.lang, limit=max(500, _ad_limit(channel)), style=channel.ai_style_prompt,
        ))
    except ProAIError as e:
        return t(e.key), back
    await state.update_data(ad_channel=channel.id, ad_brief=brief, ad_text=text)
    kb = markup([
        [btn(t("adgen.use"), Px(a="ad_use", c=channel.id))],
        [btn(t("ai.again"), Px(a="ad_again", c=channel.id))],
        _back(channel),
    ])
    return _fit(t("adgen.result") + "\n\n" + text), kb


@router.message(ProInput.ad_brief, F.text)
async def in_ad_brief(message: Message, bot: Bot, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings, ai: AIService) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    brief = message.html_text.strip()[:MAX_BRIEF]
    if len(brief) < 20:
        await message.answer(t("adgen.prompt", title=html.escape(channel.title)))
        return
    await state.set_state(None)
    working = await message.answer(t("adgen.working"))
    text, kb = await _ad_result(session, settings, state, user, channel, ai, brief)
    await _send(bot, working, text, kb)


@router.callback_query(Px.filter(F.a == "ad_again"))
async def px_ad_again(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings, ai: AIService) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    data = await state.get_data()
    if not data.get("ad_brief") or data.get("ad_channel") != channel.id:
        await cb.answer(t("adgen.expired"), show_alert=True)
        return
    await cb.answer()
    await _edit(cb, t("adgen.working"), None)
    await _edit(cb, *await _ad_result(session, settings, state, user, channel, ai, data["ad_brief"]))


@router.callback_query(Px.filter(F.a == "ad_use"))
async def px_ad_use(cb: CallbackQuery, callback_data: Px, bot: Bot, session: AsyncSession, state: FSMContext,
                    user: User, settings: Settings, publisher: Publisher) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    data = await state.get_data()
    text = data.get("ad_text")
    if not text or data.get("ad_channel") != channel.id:
        await cb.answer(t("adgen.expired"), show_alert=True)
        return
    await state.update_data(ad_text=None)
    post = await posts_repo.create_post(
        session, channel.owner_id, [channel.id], is_ad=True, options=initial_options(channel, True), text=text,
    )
    await cb.answer()
    await open_editor(bot, cb.from_user.id, session, state, user, post, publisher, note=t("adgen.opened"))


# ---- 🔍 niche research ------------------------------------------------------------------------------------------

def niche_view(channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    competitors = pro_ai.tools_settings(channel.ai_tools)["competitors"]
    lines = [t("niche.title", title=html.escape(channel.title)), "", t("niche.help"), ""]
    if competitors:
        lines.append(t("niche.list", channels=", ".join(f"@{html.escape(u)}" for u in competitors)))
    else:
        lines.append(t("niche.empty"))
    rows = []
    if competitors:
        rows.append([btn(t("niche.go"), Px(a="niche_go", c=channel.id))])
    rows += [[btn(t("niche.set"), Px(a="niche_set", c=channel.id))], _back(channel)]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a.in_({"niche", "niche_set"})))
async def px_niche(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                   settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await cb.answer()
    if callback_data.a == "niche_set":
        await state.set_state(ProInput.niche_channels)
        await state.update_data(px_channel=channel.id)
        await _edit(cb, t("niche.prompt", max=pro_ai.MAX_COMPETITORS), markup([_back(channel, "niche")]))
        return
    await state.set_state(None)
    await _edit(cb, *niche_view(channel))


@router.message(ProInput.niche_channels, F.text)
async def in_niche_channels(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    usernames = [u for u in pro_ai.parse_channel_refs(message.text or "") if u.lower() != (channel.username or "").lower()]
    if not usernames:
        await message.answer(t("niche.prompt", max=pro_ai.MAX_COMPETITORS))
        return
    channel.ai_tools = {**pro_ai.tools_settings(channel.ai_tools), "competitors": usernames}
    await session.flush()
    await state.set_state(None)
    text, kb = niche_view(channel)
    await message.answer(t("niche.saved") + "\n\n" + text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(Px.filter(F.a == "niche_go"))
async def px_niche_go(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                      settings: Settings, ai: AIService) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    usernames = pro_ai.tools_settings(channel.ai_tools)["competitors"]
    if not usernames:
        await cb.answer(t("niche.empty"), show_alert=True)
        return
    if not ai.enabled:
        await cb.answer(t("ai.disabled"), show_alert=True)
        return
    await cb.answer()
    back = markup([_back(channel, "niche")])
    await _edit(cb, t("niche.fetching", n=len(usernames)), None)
    competitors = await pro_ai.fetch_competitors(usernames)
    if not competitors:
        await _edit(cb, t("niche.err_none"), back)
        return
    own = await pro_ai.top_texts(session, channel, pro_ai.NICHE_OWN_POSTS, days=60)
    await _edit(cb, t("niche.working"), None)
    try:
        result = await _run(session, settings, user, channel, ai, "niche", lambda: ai.niche_report(
            own_title=channel.title, own_posts=own,
            competitors=[{"title": c.title, "username": c.username, "posts": c.posts} for c in competitors],
            lang=user.lang, style=channel.ai_style_prompt,
        ))
    except ProAIError as e:
        await _edit(cb, t(e.key), back)
        return
    await state.update_data(niche_channel=channel.id, niche_ideas=result["ideas"])
    skipped = [u for u in usernames if u not in {c.username for c in competitors}]
    lines = [t("niche.result", title=html.escape(channel.title)), "", result["report"]]
    if skipped:
        lines += ["", t("niche.skipped", channels=", ".join(f"@{html.escape(u)}" for u in skipped))]
    rows = []
    if result["ideas"]:
        rows.append([btn(t("niche.save_ideas", n=len(result["ideas"])), Px(a="niche_ideas", c=channel.id))])
    rows.append(_back(channel, "niche"))
    await _edit(cb, _fit("\n".join(lines)), markup(rows))


@router.callback_query(Px.filter(F.a == "niche_ideas"))
async def px_niche_ideas(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                         settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    data = await state.get_data()
    ideas = data.get("niche_ideas")
    if not ideas or data.get("niche_channel") != channel.id:
        await cb.answer(t("niche.expired"), show_alert=True)
        return
    await state.update_data(niche_ideas=None)
    await ideas_service.save(session, channel, ideas)
    await cb.answer(t("niche.ideas_saved", n=len(ideas)), show_alert=True)
    if cb.message is not None:
        await cb.message.edit_reply_markup(reply_markup=markup([
            [btn(t("pro.ideas"), Px(a="ideas", c=channel.id))], _back(channel, "niche"),
        ]))


# ---- 🤖 AI answerer in comments ---------------------------------------------------------------------------------

def answer_view(channel: Channel) -> tuple[str, InlineKeyboardMarkup]:
    s = pro_ai.tools_settings(channel.ai_tools)
    lines = [t("aians.title", title=html.escape(channel.title)), "", t("aians.help"), ""]
    lines.append(t("aians.on") if s["answer"] else t("aians.off"))
    if s["answer"] and s["answer_out"]:
        lines.append(t("aians.paused"))
    if not channel.discussion_chat_id:
        lines.append(t("aians.no_group"))
    lines += ["", t("aians.kb_line", kb=f"<blockquote>{html.escape(snippet(s['kb'], 600))}</blockquote>")
              if s["kb"].strip() else t("aians.kb_empty")]
    c = channel.id
    rows = [
        [btn(on(s["answer"]) + t("aians.toggle"), Px(a="ans_t", c=c))],
        [btn(t("aians.kb_btn"), Px(a="ans_kb", c=c))],
        _back(channel),
    ]
    return "\n".join(lines), markup(rows)


@router.callback_query(Px.filter(F.a.in_({"ans", "ans_t"})))
async def px_answer(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                    settings: Settings) -> None:
    # The screen needs the paid plan or trial like the other PRO tools; turning it off is always allowed.
    channel = await _channel(cb, callback_data, session, user, settings, paid=callback_data.a == "ans")
    if channel is None:
        return
    s = pro_ai.tools_settings(channel.ai_tools)
    if callback_data.a == "ans_t":
        turning_on = not s["answer"]
        if turning_on:
            if not channel.discussion_chat_id:
                await cb.answer(t("cm.auto_need_group"), show_alert=True)
                return
            if not s["kb"].strip():
                await cb.answer(t("aians.need_kb"), show_alert=True)
                return
            if await _channel(cb, callback_data, session, user, settings) is None:
                return
        channel.ai_tools = {**s, "answer": turning_on, "answer_out": False}
        await session.flush()
        if turning_on:
            await cb.answer(t("aians.on_done"), show_alert=True)
    await state.set_state(None)
    if callback_data.a != "ans_t" or not pro_ai.tools_settings(channel.ai_tools)["answer"]:
        await cb.answer()
    await _edit(cb, *answer_view(channel))


@router.callback_query(Px.filter(F.a == "ans_kb"))
async def px_answer_kb(cb: CallbackQuery, callback_data: Px, session: AsyncSession, state: FSMContext, user: User,
                       settings: Settings) -> None:
    channel = await _channel(cb, callback_data, session, user, settings)
    if channel is None:
        return
    await state.set_state(ProInput.answer_kb)
    await state.update_data(px_channel=channel.id)
    await cb.answer()
    await _edit(cb, t("aians.kb_prompt", max=pro_ai.MAX_KB), markup([_back(channel, "ans")]))


@router.message(ProInput.answer_kb, F.text)
async def in_answer_kb(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    channel = await _input_channel(message, session, state, user)
    if channel is None:
        return
    text = (message.text or "").strip()
    if len(text) < 20 or len(text) > pro_ai.MAX_KB:
        await message.answer(t("aians.kb_prompt", max=pro_ai.MAX_KB))
        return
    channel.ai_tools = {**pro_ai.tools_settings(channel.ai_tools), "kb": text}
    await session.flush()
    await state.set_state(None)
    view, kb = answer_view(channel)
    await message.answer(t("aians.kb_saved") + "\n\n" + view, reply_markup=kb, disable_web_page_preview=True)


# ---- shared -----------------------------------------------------------------------------------------------------

async def _send(bot: Bot, working: Message, text: str, kb: InlineKeyboardMarkup) -> None:
    """Replace the «⏳» message with the result; if Telegram rejects the AI's HTML, show it escaped."""
    try:
        await bot.edit_message_text(text, chat_id=working.chat.id, message_id=working.message_id, reply_markup=kb,
                                    disable_web_page_preview=True)
    except TelegramBadRequest:
        await bot.edit_message_text(html.escape(text), chat_id=working.chat.id, message_id=working.message_id,
                                    reply_markup=kb, disable_web_page_preview=True)


@router.message(ProInput.ad_brief)
@router.message(ProInput.niche_channels)
@router.message(ProInput.answer_kb)
async def in_wrong(message: Message) -> None:
    await message.answer(t("err.expected_input"))

