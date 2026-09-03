"""Ports to the outside world (ARCHITECTURE §6.1).

Services never talk to Telegram directly: they receive a `TelegramGateway`, so the bot can
pass an aiogram adapter and the tests a fake. Later stages add `send_message` and
`send_document` to the protocol; a gateway only has to implement what its callers use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TelegramFile:
    """Answer of `getFile`: where the file lives on Telegram's side and how big it is."""

    file_path: str
    file_size: int | None = None


class TelegramGateway(Protocol):
    """The part of the Telegram API the services layer needs."""

    async def get_file(self, file_id: str) -> TelegramFile: ...

    async def download_file(self, file_path: str, destination: Path) -> None:
        """Write the file to `destination`; the caller creates the parent directory."""
        ...
