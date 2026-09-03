"""`TelegramGateway` implemented over an aiogram `Bot` (ARCHITECTURE §6.1, §9.1)."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from romantika.services.gateways import TelegramFile

logger = logging.getLogger(__name__)


class AiogramTelegramGateway:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def get_file(self, file_id: str) -> TelegramFile:
        info = await self.bot.get_file(file_id)
        if not info.file_path:
            raise RuntimeError(f"Telegram returned no file_path for {file_id}")
        return TelegramFile(file_path=info.file_path, file_size=info.file_size)

    async def download_file(self, file_path: str, destination: Path) -> None:
        await self.bot.download_file(file_path, destination=destination)

    async def send_message(self, chat_id: int, text: str) -> None:
        from romantika.bot.send import safe_send

        sent = await safe_send(self.bot, chat_id, text)
        if sent is None:
            raise RuntimeError(f"message to {chat_id} was not delivered")

    async def send_document(self, chat_id: int, path: Path, caption: str | None = None) -> None:
        try:
            await self.bot.send_document(chat_id, FSInputFile(path), caption=caption, parse_mode="HTML")
        except TelegramAPIError as exc:
            logger.error("send_document_failed", extra={"chat_id": chat_id, "path": str(path), "error": str(exc)})
            raise
