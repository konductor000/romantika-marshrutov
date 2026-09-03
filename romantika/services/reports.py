"""Reports: everything a participant sends the bot (DOMAIN §2).

A report is never physically deleted — «это не отчёт» sets `deleted_at` and the stamp of the
week is recomputed from what is left. Media rows are created here but downloaded by
`media.MediaStore`, so accepting a report never waits on the network.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models
from romantika.domain import rules
from romantika.domain.calendar import to_moscow
from romantika.domain.types import ReportKind, StampLevel
from romantika.services import content, freezes, media, people, stamps


@dataclass(frozen=True, slots=True)
class IncomingFile:
    """One attachment of a Telegram message, before we have downloaded it."""

    kind: ReportKind
    file_id: str
    file_unique_id: str | None = None
    mime: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """A message the bot decided is a report (not a command, button or dialog answer)."""

    kind: ReportKind
    text: str | None = None
    tg_chat_id: int | None = None
    tg_message_id: int | None = None
    files: list[IncomingFile] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AcceptResult:
    """What the bot has to tell the participant, and what to hand to the media download."""

    report_id: int
    week_number: int | None
    out_of_week: bool
    level: StampLevel
    stamp_level: StampLevel | None
    freeze_granted: bool
    media_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class FixResult:
    """«Это был максимум/минимум». `reason` is a code; the bot turns it into Russian."""

    ok: bool
    stamp_level: StampLevel | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CancelResult:
    """«Это не отчёт, а сообщение Миле»: the stamp level left after the recomputation."""

    ok: bool
    stamp_level: StampLevel | None
    reason: str | None = None


async def accept(
    session: AsyncSession,
    *,
    season_id: int,
    user_id: int,
    message: IncomingMessage,
    now: datetime,
) -> AcceptResult:
    """Store the report, stamp the week and grant the freeze for the first maximum.

    Outside a week (before the season, between weeks, after the last one) the message is
    still stored — as a letter to Mila with no week and no stamp (DOMAIN §2, §10.2).
    """
    season = await content.require_season(session, season_id)
    await people.ensure_member(session, season_id, user_id, now=now)
    week = await content.current_week(session, season_id, today=to_moscow(now).date())
    # Outside a week the message is a letter, not a report: it is stored as `other` at the
    # minimum level so nothing downstream mistakes it for a week's work (ARCHITECTURE §6).
    kind = message.kind if week is not None else ReportKind.OTHER
    level = rules.report_level(kind)

    report = models.Report(
        season_id=season_id,
        user_id=user_id,
        week_id=None if week is None else week.id,
        kind=kind.value,
        text=message.text,
        level=level.value,
        tg_chat_id=message.tg_chat_id,
        tg_message_id=message.tg_message_id,
        created_at=now,
    )
    session.add(report)
    await session.flush()

    media_rows: list[models.Media] = []
    for item in message.files:
        row = models.Media(
            report_id=report.id,
            tg_file_id=item.file_id,
            tg_file_unique_id=item.file_unique_id,
            mime=item.mime,
            size=item.size,
            width=item.width,
            height=item.height,
            path=media.new_relative_path(
                season_slug=season.slug,
                user_id=user_id,
                suffix=media.suffix_for(kind=item.kind, mime=item.mime),
            ),
            created_at=now,
        )
        session.add(row)
        media_rows.append(row)
    if media_rows:
        # The uuid primary key is a Python-side default: it exists only after the flush.
        await session.flush()
    media_ids: list[uuid.UUID] = [row.id for row in media_rows]

    if week is None:
        return AcceptResult(
            report_id=report.id,
            week_number=None,
            out_of_week=True,
            level=level,
            stamp_level=None,
            freeze_granted=False,
            media_ids=media_ids,
        )

    stamp = await stamps.merge(
        session,
        season_id=season_id,
        user_id=user_id,
        week_id=week.id,
        week_title=week.title,
        level=level,
        now=now,
    )
    freeze_granted = False
    if stamp.upgraded_to_max:
        freeze_granted = await freezes.grant(
            session,
            season_id=season_id,
            user_id=user_id,
            reason=models.FreezeReason.MAX,
            granted_by=None,
            now=now,
        )
    return AcceptResult(
        report_id=report.id,
        week_number=week.number,
        out_of_week=False,
        level=level,
        stamp_level=stamp.level,
        freeze_granted=freeze_granted,
        media_ids=media_ids,
    )


async def fix_level(
    session: AsyncSession,
    *,
    season_id: int,
    user_id: int,
    week_number: int,
    level: StampLevel,
    now: datetime,
) -> FixResult:
    """The «это был максимум/минимум» buttons: upgrade only, and only with a report."""
    week = await content.week_by_number(session, season_id, week_number)
    if week is None:
        return FixResult(ok=False, stamp_level=None, reason="no_week")

    current = await stamps.get_level(session, user_id=user_id, week_id=week.id)
    if not await _has_report(session, user_id=user_id, week_id=week.id):
        return FixResult(ok=False, stamp_level=current, reason="no_report")
    if current is StampLevel.MAX and level is StampLevel.MIN:
        return FixResult(ok=False, stamp_level=StampLevel.MAX, reason="max_is_not_downgraded")

    stamp = await stamps.merge(
        session,
        season_id=season_id,
        user_id=user_id,
        week_id=week.id,
        week_title=week.title,
        level=level,
        now=now,
    )
    if stamp.upgraded_to_max:
        await freezes.grant(
            session,
            season_id=season_id,
            user_id=user_id,
            reason=models.FreezeReason.MAX,
            granted_by=None,
            now=now,
        )
    return FixResult(ok=True, stamp_level=stamp.level, reason=None)


async def cancel(session: AsyncSession, *, user_id: int, report_id: int, now: datetime) -> CancelResult:
    """«Это не отчёт, а сообщение Миле»: mark it deleted and recompute the week's stamp.

    The row itself stays forever; a stamp Mila set by hand is not touched (DOMAIN §2).
    """
    report = await session.get(models.Report, report_id)
    if report is None or report.user_id != user_id:
        return CancelResult(ok=False, stamp_level=None, reason="not_yours")
    if report.deleted_at is not None:
        return CancelResult(ok=False, stamp_level=None, reason="already_cancelled")

    report.deleted_at = now
    await session.flush()
    if report.week_id is None:
        return CancelResult(ok=True, stamp_level=None)

    query = select(models.Stamp).where(models.Stamp.user_id == user_id, models.Stamp.week_id == report.week_id)
    stamp = (await session.execute(query)).scalar_one_or_none()
    if stamp is None:
        return CancelResult(ok=True, stamp_level=None)
    if stamp.source == models.StampSource.ADMIN.value:
        return CancelResult(ok=True, stamp_level=StampLevel(stamp.level))

    levels = await _remaining_levels(session, user_id=user_id, week_id=report.week_id)
    if not levels:
        await session.delete(stamp)
        await session.flush()
        return CancelResult(ok=True, stamp_level=None)

    level = StampLevel.MAX if StampLevel.MAX in levels else StampLevel.MIN
    stamp.level = level.value
    await session.flush()
    return CancelResult(ok=True, stamp_level=level)


async def _has_report(session: AsyncSession, *, user_id: int, week_id: int) -> bool:
    query = select(models.Report.id).where(
        models.Report.user_id == user_id,
        models.Report.week_id == week_id,
        models.Report.deleted_at.is_(None),
    )
    return (await session.execute(query.limit(1))).first() is not None


async def _remaining_levels(session: AsyncSession, *, user_id: int, week_id: int) -> set[StampLevel]:
    query = select(models.Report.level).where(
        models.Report.user_id == user_id,
        models.Report.week_id == week_id,
        models.Report.deleted_at.is_(None),
    )
    return {StampLevel(level) for level in (await session.execute(query)).scalars()}
