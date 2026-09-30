"""Billing Mini App: Telegram initData auth, JSON API and the static frontend."""
from __future__ import annotations

from aiogram import Bot
from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker

from flowpost.config import Settings
from flowpost.services.ai import AIService

SETTINGS_KEY = web.AppKey("settings", Settings)
BOT_KEY = web.AppKey("bot", Bot)
SESSIONMAKER_KEY = web.AppKey("sessionmaker", async_sessionmaker)
AI_KEY = web.AppKey("ai", AIService)
