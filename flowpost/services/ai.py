"""AI assistant for post texts, powered by Claude (Anthropic API)."""
from __future__ import annotations

import base64
import logging

import anthropic
from anthropic import AsyncAnthropic

from flowpost.config import Settings
from flowpost.services.html_sanitize import sanitize_html

log = logging.getLogger(__name__)

ACTIONS = ("format", "shorten", "fix", "emoji", "custom", "screenshot", "translate", "rss")

BASE_PROMPT = """You are the editor inside FlowPost, a Telegram channel autoposting bot. You prepare posts that go straight into a Telegram channel.

Output rules:
- Reply with the final post text only: no preamble, no explanations, no quotes around it, no code fences.
- Formatting is Telegram HTML. Allowed tags: <b>, <i>, <u>, <s>, <a href="...">, <code>, <pre>, <blockquote>, <tg-spoiler>. Do not use Markdown, <p>, <br>, <ul>, <li> or headings; use plain line breaks, and "•" or emoji for lists.
- Keep every fact, name, number, date, address, price, link and contact exactly as given. Never invent details that are not in the source.
- Write in the same language as the source post. If there is no source text, write in the language named in the request.
- Respect the character limit given in the request.
- Emoji are welcome but in moderation; the tone should suit a news/community channel unless the channel style says otherwise."""

TASKS = {
    "format": "Turn the raw text into a polished, ready-to-publish Telegram post: a catchy first line in bold, short readable paragraphs, key details highlighted.",
    "shorten": "Make the post noticeably shorter (roughly half) while keeping all key facts and the call to action.",
    "fix": "Fix spelling, grammar and punctuation only. Keep the wording, structure and formatting otherwise unchanged.",
    "emoji": "Add fitting emoji to make the post livelier. Do not change the wording.",
    "custom": "Edit the post following the channel owner's instruction.",
    "translate": "Translate the post into the language named in the instruction; this overrides the rule about writing in the source language. Keep the HTML formatting, links, emoji, line breaks and meaning; translate naturally, not word for word. If the post is already in that language, return it unchanged.",
    "rss": "The post is an item from a news feed: its title, summary and link. Write a ready-to-publish Telegram post about it for this channel: a bold first line, then a few short paragraphs with the key facts from the summary, and finish with the item's link as a short «read more» <a href> in the post's language. Use only what the item says.",
    "screenshot": "The image is a screenshot (for example a news item, a message or an announcement). Extract its meaningful content and write a ready-to-publish Telegram post based on it. Ignore interface elements, timestamps and usernames unless they matter. If a draft post is also given, use it as extra context.",
}

LANG_NAMES = {
    "uk": "Ukrainian", "en": "English", "pl": "Polish", "de": "German",
    "es": "Spanish", "fr": "French", "it": "Italian", "pt": "Portuguese",
}

PLAN_SEPARATOR = "====="
PLAN_PROMPT = f"""You are the content strategist inside FlowPost, a Telegram channel autoposting bot. You plan a week of posts for one channel.

Output rules:
- Write exactly the requested number of ready-to-publish posts, separated by a line containing only {PLAN_SEPARATOR}.
- No numbering, preamble or explanations: only the posts and the separators.
- Each post is Telegram HTML (<b>, <i>, <u>, <s>, <a href="...">, <blockquote>), starts with a bold first line that works as its title, and fits in 900 characters.
- Vary the formats across the week: news or useful tips, a question to the audience, a list, a story, a behind-the-scenes post and so on.
- Match the channel's topic, language and tone from its title, style guide and example posts. Do not invent specific facts, prices, dates or links; where a post needs one, leave a clear placeholder like [дата] in the post's language."""


class AIError(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


class AIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: AsyncAnthropic | None = None
        if settings.ai_enabled:
            self.client = AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),  # type: ignore[union-attr]
                timeout=180.0,
                max_retries=2,
            )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _build_request(
        self,
        action: str,
        *,
        text: str,
        lang: str,
        limit: int,
        style: str | None,
        instruction: str | None,
        image: tuple[bytes, str] | None,
    ) -> dict:
        system: list[dict] = [{"type": "text", "text": BASE_PROMPT, "cache_control": {"type": "ephemeral"}}]
        if style and style.strip():
            system.append({"type": "text", "text": f"Channel style guide from the channel owner:\n{style.strip()}"})

        request = (
            f"<task>{TASKS[action]}</task>\n"
            f"<limit>At most {limit} characters including line breaks.</limit>\n"
            f"<fallback_language>{LANG_NAMES.get(lang, 'Ukrainian')}</fallback_language>\n"
        )
        if instruction:
            request += f"<instruction>{instruction.strip()}</instruction>\n"
        request += f"<post>\n{text.strip()}\n</post>" if text.strip() else "<post>(empty)</post>"

        content: list[dict] = []
        if image:
            data, media_type = image
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
            })
        content.append({"type": "text", "text": request})
        return self._kwargs(system, content)

    async def generate(
        self,
        action: str,
        *,
        text: str,
        lang: str,
        limit: int,
        style: str | None = None,
        instruction: str | None = None,
        image: tuple[bytes, str] | None = None,
    ) -> str:
        if self.client is None:
            raise AIError("ai.disabled")
        if action not in TASKS:
            raise ValueError(action)
        kwargs = self._build_request(
            action, text=text, lang=lang, limit=limit, style=style, instruction=instruction, image=image
        )
        result = sanitize_html(await self._complete(kwargs))
        if not result:
            raise AIError("ai.empty")
        return result

    async def translate(self, text: str, target_lang: str, *, limit: int) -> str:
        return await self.generate(
            "translate", text=text, lang=target_lang, limit=limit,
            instruction=f"Target language: {LANG_NAMES.get(target_lang, target_lang)}.",
        )

    async def content_plan(
        self, *, channel_title: str, style: str | None, examples: list[str], lang: str, count: int = 7,
    ) -> list[str]:
        """`count` draft posts for the channel's coming week, written in the spirit of its best recent posts."""
        if self.client is None:
            raise AIError("ai.disabled")
        system: list[dict] = [{"type": "text", "text": PLAN_PROMPT, "cache_control": {"type": "ephemeral"}}]
        if style and style.strip():
            system.append({"type": "text", "text": f"Channel style guide from the channel owner:\n{style.strip()}"})
        request = (
            f"<channel>{channel_title}</channel>\n"
            f"<count>{count}</count>\n"
            f"<fallback_language>{LANG_NAMES.get(lang, 'Ukrainian')}</fallback_language>\n"
        )
        if examples:
            request += "<best_recent_posts>\n" + "\n---\n".join(e.strip() for e in examples) + "\n</best_recent_posts>"
        else:
            request += "<best_recent_posts>(none yet)</best_recent_posts>"
        raw = await self._complete(self._kwargs(system, [{"type": "text", "text": request}]))
        posts = [sanitize_html(chunk) for chunk in raw.split(PLAN_SEPARATOR)]
        posts = [p for p in posts if p]
        if not posts:
            raise AIError("ai.empty")
        return posts[:count]

    def _kwargs(self, system: list[dict], content: list[dict]) -> dict:
        kwargs: dict = {
            "model": self.settings.anthropic_model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": self.settings.ai_effort},
        }
        if self.settings.ai_fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        return kwargs

    async def _complete(self, kwargs: dict) -> str:
        """Run one request and return the reply's text; failures become AIError with an i18n key."""
        try:
            response = await self.client.beta.messages.create(**kwargs)  # type: ignore[union-attr]
        except anthropic.RateLimitError as e:
            log.warning("Anthropic rate limit: %s", e)
            raise AIError("ai.busy") from e
        except anthropic.APIStatusError as e:
            log.error("Anthropic API error %s: %s", e.status_code, e.message)
            raise AIError("ai.failed") from e
        except anthropic.APIConnectionError as e:
            log.error("Anthropic connection error: %s", e)
            raise AIError("ai.failed") from e
        if response.stop_reason == "refusal":
            raise AIError("ai.refused")
        return "".join(block.text for block in response.content if block.type == "text").strip()
