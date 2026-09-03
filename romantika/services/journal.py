"""The season journal of one participant (DOMAIN §7): bot preview, Mini App and PDF.

One view model for all three, so the PDF can never say something the bot does not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models
from romantika.domain.types import StampLevel
from romantika.services import achievements, content, facts, people, stamps, wishes, words
from romantika.services.content import SeasonDTO
from romantika.services.facts import FactDTO
from romantika.services.people import UserDTO
from romantika.services.words import UserWord


@dataclass(frozen=True, slots=True)
class JournalWeek:
    """A week the participant has a stamp for, with a line they wrote about it."""

    number: int
    title: str
    level: StampLevel
    quote: str


@dataclass(frozen=True, slots=True)
class JournalMedia:
    """A file of a report. `path` only points at a real file once `downloaded` is true."""

    media_id: uuid.UUID
    path: str
    downloaded: bool


@dataclass(frozen=True, slots=True)
class JournalView:
    user: UserDTO | None
    season: SeasonDTO
    weeks: list[JournalWeek]
    media: list[JournalMedia]
    achievements: list[str]
    words: list[UserWord]
    facts: list[FactDTO]
    wish: str | None


async def build(session: AsyncSession, *, season_id: int, user_id: int, today: date) -> JournalView:
    """Collect the stamped weeks, the media, the achievements and the wish of one person.

    `today` keeps the journal honest about weeks that have not happened yet: a stamp Mila
    set on a future week is not shown before that week starts.
    """
    season = await content.require_season(session, season_id)
    weeks = {week.number: week for week in await content.weeks(session, season_id)}
    levels = await stamps.for_user(session, season_id=season_id, user_id=user_id)
    quotes = await _quotes(session, season_id=season_id, user_id=user_id)

    journal_weeks = [
        JournalWeek(
            number=number,
            title=weeks[number].title,
            level=level,
            quote=quotes.get(weeks[number].id, ""),
        )
        for number, level in sorted(levels.items())
        if number in weeks and weeks[number].starts_on <= today
    ]
    return JournalView(
        user=await people.get_user(session, user_id),
        season=season,
        weeks=journal_weeks,
        media=await _media(session, season_id=season_id, user_id=user_id),
        achievements=await achievements.labels(session, season_id=season_id, user_id=user_id),
        words=await words.for_user(session, season_id=season_id, user_id=user_id),
        facts=await facts.list_active(session, season_id),
        wish=await wishes.get_wish(session, season_id, user_id),
    )


async def _quotes(session: AsyncSession, *, season_id: int, user_id: int) -> dict[int, str]:
    """`{week_id: text}` — the last thing the participant wrote in that week."""
    query = (
        select(models.Report.week_id, models.Report.text)
        .where(
            models.Report.season_id == season_id,
            models.Report.user_id == user_id,
            models.Report.week_id.is_not(None),
            models.Report.deleted_at.is_(None),
            models.Report.text.is_not(None),
            models.Report.text != "",
        )
        .order_by(models.Report.created_at, models.Report.id)
    )
    # A later report of the same week overwrites the earlier one: the quote is the last line.
    quotes: dict[int, str] = {}
    for week_id, text in (await session.execute(query)).tuples().all():
        if week_id is not None and text:
            quotes[week_id] = text
    return quotes


async def _media(session: AsyncSession, *, season_id: int, user_id: int) -> list[JournalMedia]:
    """Files of week reports that were neither cancelled nor hidden.

    A message sent outside a week is a letter to Mila and not a report (DOMAIN §2), so its
    files stay out of the season journal. `downloaded` says whether the file is already on
    our disk: the row is created by `reports.accept` and filled in by `MediaStore.download`,
    so the PDF must skip a path that is still only a promise.
    """
    query = (
        select(models.Media.id, models.Media.path, models.Media.downloaded_at)
        .join(models.Report, models.Report.id == models.Media.report_id)
        .where(
            models.Report.season_id == season_id,
            models.Report.user_id == user_id,
            models.Report.week_id.is_not(None),
            models.Report.deleted_at.is_(None),
            models.Media.hidden_at.is_(None),
        )
        .order_by(models.Media.created_at, models.Media.id)
    )
    return [
        JournalMedia(media_id=media_id, path=path, downloaded=downloaded_at is not None)
        for media_id, path, downloaded_at in (await session.execute(query)).all()
    ]
