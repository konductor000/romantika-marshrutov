"""Participant media on our own disk (DOMAIN §2, ARCHITECTURE §6.1).

A file is downloaded once, verified by its sha256 and never deleted — «removal» is
`hidden_at`. The download writes to `<name>.part` and renames it into place, so a crash
mid-download can never leave a half file that later looks complete.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models
from romantika.domain.types import ReportKind
from romantika.services.gateways import TelegramGateway

#: Extensions Telegram's mime types do not map to the way we want them to.
_SUFFIX_BY_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "application/octet-stream": ".bin",
}

#: Fallback per kind when neither the mime type nor Telegram's path says anything.
_SUFFIX_BY_KIND: dict[ReportKind, str] = {
    ReportKind.PHOTO: ".jpg",
    ReportKind.VIDEO: ".mp4",
    ReportKind.VIDEO_NOTE: ".mp4",
    ReportKind.VOICE: ".ogg",
    ReportKind.AUDIO: ".mp3",
}

_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MediaDTO:
    """A downloaded file: where it lies under the media root and what it hashes to."""

    media_id: uuid.UUID
    path: str
    sha256: str | None
    size: int | None


def suffix_for(*, kind: ReportKind, mime: str | None) -> str:
    """The extension a file of this kind and mime type gets on our disk."""
    if mime:
        known = _SUFFIX_BY_MIME.get(mime)
        if known:
            return known
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed
    return _SUFFIX_BY_KIND.get(kind, ".bin")


def new_relative_path(*, season_slug: str, user_id: int, suffix: str) -> str:
    """`<season_slug>/<user_id>/<uuid>.<ext>` — unique, and readable in a backup listing."""
    return f"{season_slug}/{user_id}/{uuid.uuid4()}{suffix}"


class MediaStore:
    """The media directory (`MEDIA_DIR`). The only place that writes participant files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def full_path(self, relative: str) -> Path:
        return self.root / relative

    async def download(
        self,
        session: AsyncSession,
        media_id: uuid.UUID,
        telegram: TelegramGateway,
        *,
        now: datetime,
    ) -> MediaDTO:
        """Fetch the file from Telegram unless we already have it. Idempotent by design.

        The bot calls this right after `reports.accept`; when it raises, the caller enqueues
        a `media_download` job and the worker calls it again with the same `media_id`.
        """
        row = await session.get(models.Media, media_id)
        if row is None:
            raise LookupError(f"media {media_id} does not exist")
        if row.downloaded_at is not None and self.full_path(row.path).exists():
            return MediaDTO(media_id=row.id, path=row.path, sha256=row.sha256, size=row.size)

        remote = await telegram.get_file(row.tg_file_id)
        relative = _with_suffix(row.path, PurePosixPath(remote.file_path).suffix)
        target = self.full_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        await telegram.download_file(remote.file_path, part)

        digest, size = await asyncio.to_thread(_finalize, part, target)
        row.path = relative
        row.sha256 = digest
        row.size = size
        row.downloaded_at = now
        await session.flush()
        return MediaDTO(media_id=row.id, path=relative, sha256=digest, size=size)


def _with_suffix(relative: str, suffix: str) -> str:
    """Keep the generated uuid, take the extension Telegram actually served."""
    path = PurePosixPath(relative)
    if not suffix or path.suffix == suffix:
        return relative
    return str(path.with_suffix(suffix))


def _finalize(part: Path, target: Path) -> tuple[str, int]:
    """Hash the downloaded part file and move it into place atomically (same filesystem)."""
    digest = hashlib.sha256()
    size = 0
    with part.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    part.replace(target)
    return digest.hexdigest(), size
