"""Job execution: one job per call, each step in its own transaction (ARCHITECTURE §9.1)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from romantika.domain.calendar import to_moscow
from romantika.pdf.journal import render_journal_pdf
from romantika.services import content, jobs, journal, passport
from romantika.services.gateways import TelegramGateway
from romantika.services.media import MediaStore

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, dict[str, Any], "Context"], Awaitable[dict[str, Any] | None]]


class Context:
    def __init__(self, *, telegram: TelegramGateway, media_store: MediaStore, now: datetime) -> None:
        self.telegram = telegram
        self.media_store = media_store
        self.now = now


async def handle_media_download(session: AsyncSession, payload: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    media_id = uuid.UUID(str(payload["media_id"]))
    dto = await ctx.media_store.download(session, media_id, ctx.telegram, now=ctx.now)
    return {"path": dto.path}


async def handle_journal_pdf(session: AsyncSession, payload: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    user_id = int(payload["user_id"])
    season_id = int(payload["season_id"])
    chat_id = int(payload.get("chat_id", user_id))
    today = to_moscow(ctx.now).date()
    season = await content.require_season(session, season_id)
    view = await journal.build(session, season_id=season_id, user_id=user_id, today=today)
    level = (await passport.build(session, season_id=season_id, user_id=user_id, today=today)).level
    pdf = render_journal_pdf(view, media_root=ctx.media_store.root, level=level)

    relative = f"journals/{season.slug}/{user_id}-{ctx.now:%Y%m%d-%H%M%S}.pdf"
    target = ctx.media_store.full_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    caption = f"📔 Твой журнал сезона «{season.title}»"
    await ctx.telegram.send_document(chat_id, target, caption)
    return {"result_path": relative, "bytes": len(pdf)}


async def handle_broadcast(session: AsyncSession, payload: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    text = str(payload["text"])
    sent = 0
    for user_id in payload.get("user_ids", []):
        try:
            await ctx.telegram.send_message(int(user_id), text)
            sent += 1
        except Exception as exc:
            logger.warning("broadcast_not_delivered", extra={"user_id": user_id, "error": str(exc)})
    return {"sent": sent}


HANDLERS: dict[str, Handler] = {
    "media_download": handle_media_download,
    "journal_pdf": handle_journal_pdf,
    "broadcast": handle_broadcast,
}


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram: TelegramGateway,
    media_store: MediaStore,
    now: datetime,
) -> str | None:
    """Claim one job, run it, record the outcome. Returns the job kind, or None when idle."""
    async with session_factory() as session, session.begin():
        job = await jobs.claim(session, now=now)
        if job is None:
            return None
        job_id, kind, payload = job.id, job.kind, dict(job.payload)

    handler = HANDLERS.get(kind)
    error: str | None = None
    result: dict[str, Any] | None = None
    if handler is None:
        error = f"unknown job kind {kind!r}"
    else:
        try:
            async with session_factory() as session, session.begin():
                result = await handler(session, payload, Context(telegram=telegram, media_store=media_store, now=now))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning("job_failed", extra={"job_id": job_id, "kind": kind, "error": error})

    async with session_factory() as session, session.begin():
        status = await jobs.finish(session, job_id, error=error, now=now, result=result)
    logger.info("job_finished", extra={"job_id": job_id, "kind": kind, "status": status.value})
    return kind
