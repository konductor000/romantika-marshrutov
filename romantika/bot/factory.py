"""Build the aiogram `Bot` the way every process needs it (proxy, timeouts)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from romantika.config import Settings


def make_bot(settings: Settings) -> Bot:
    """A Bot that reaches Telegram through `TELEGRAM_PROXY` (or `HTTPS_PROXY`) when set.

    aiohttp does not read proxy variables from the environment on its own; on the VPS
    Telegram is reachable only through the host proxy, so this is not optional there.
    """
    proxy = settings.telegram_proxy or None
    session = AiohttpSession(proxy=proxy, timeout=60) if proxy else AiohttpSession(timeout=60)
    return Bot(settings.bot_token, session=session)
