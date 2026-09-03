"""Mila replies to a forwarded report or letter → the answer goes to its author."""

from __future__ import annotations

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.bot.send import safe_send
from romantika.services import links
from romantika.texts import ru


async def relay_reply(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    is_admin: bool,
    now: datetime,
) -> None:
    from aiogram.dispatcher.event.bases import SkipHandler

    replied = message.reply_to_message
    if not is_admin or replied is None or not message.text:
        raise SkipHandler
    link = await links.lookup(session, admin_chat_id=message.chat.id, admin_message_id=replied.message_id)
    if link is None:
        raise SkipHandler
    delivered = await safe_send(bot, link.user_id, ru.reply_to_author(message.text))
    await safe_send(bot, message.chat.id, ru.REPLY_DELIVERED if delivered else ru.REPLY_FAILED)


def build() -> Router:
    router = Router(name="admin_reply")
    router.message.register(relay_reply, F.reply_to_message, F.text, ~F.text.startswith("/"))
    return router
