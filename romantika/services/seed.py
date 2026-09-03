"""Import a season description (`data/seasons/*.json`) into the database.

Idempotent: rerunning updates the rows in place, so content fixes — including a moved
calendar — can be re-imported. Rows the file no longer describes are never deleted (stamps
and reports point at them); `SeedResult` counts them as `*_stale` instead.
Like every service, it flushes but never commits — the caller owns the transaction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SeedResult:
    """What one import did, for the CLI output and tests."""

    season_id: int
    slug: str
    created: bool
    weeks: int
    """Weeks of the season in the database after the import, not lines in the file."""
    weeks_created: int
    weeks_stale: int
    """Weeks left in the database that the file no longer describes; seed never deletes."""
    achievement_types: int
    achievement_types_created: int
    achievement_types_stale: int


class SeedError(ValueError):
    """A season file is missing a key without which the content makes no sense."""


def _as_date(payload: dict[str, Any], key: str, where: str) -> date:
    return date.fromisoformat(_required(payload, key, where))


def _text(payload: dict[str, Any], key: str) -> str:
    """An optional text field: absent means empty."""
    value = payload.get(key)
    return "" if value is None else str(value)


def _required(payload: dict[str, Any], key: str, where: str) -> str:
    """A field the participants would notice if it were empty."""
    value = payload.get(key)
    filled = "" if value is None else str(value).strip()
    if not filled:
        raise SeedError(f"{where}: required field '{key}' is missing or empty")
    return filled


async def import_season(session: AsyncSession, path: Path) -> SeedResult:
    """Upsert a season, its weeks and its achievement types. Slug comes from the file name."""
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    slug = Path(path).stem
    daily: dict[str, Any] = payload.get("daily") or {}

    season = (await session.execute(select(models.Season).where(models.Season.slug == slug))).scalar_one_or_none()
    created = season is None
    if season is None:
        season = models.Season(slug=slug, status=models.SeasonStatus.DRAFT.value)
        session.add(season)

    season.title = _required(payload, "season", slug)
    season.title_accusative = _required(payload, "season_about", slug)
    season.hashtag = _required(payload, "hashtag", slug)
    season.starts_on = _as_date(payload, "start", slug)
    season.ends_on = _as_date(payload, "end", slug)
    season.daily_kind = daily.get("kind")
    season.daily_title = _text(daily, "title")
    season.daily_note = _text(daily, "note")
    await session.flush()

    weeks_created, weeks_stale = await _import_weeks(session, season, payload.get("weeks") or [])
    types_created, types_stale = await _import_achievement_types(session, season, payload.get("achievements") or [])
    await session.flush()

    result = SeedResult(
        season_id=season.id,
        slug=slug,
        created=created,
        weeks=await _count(session, models.Week, season.id),
        weeks_created=weeks_created,
        weeks_stale=weeks_stale,
        achievement_types=await _count(session, models.AchievementType, season.id),
        achievement_types_created=types_created,
        achievement_types_stale=types_stale,
    )
    if result.weeks_stale or result.achievement_types_stale:
        logger.warning(
            "season %s: %d week(s) and %d achievement type(s) in the database are not in the file; "
            "seed never deletes, remove them by hand if they are wrong",
            slug,
            result.weeks_stale,
            result.achievement_types_stale,
        )
    return result


async def _count(session: AsyncSession, model: type[models.Week] | type[models.AchievementType], season_id: int) -> int:
    """How many rows the season really has, so a caller can compare it with the file."""
    query = select(func.count()).select_from(model).where(model.season_id == season_id)
    return (await session.execute(query)).scalar_one()


async def _import_weeks(session: AsyncSession, season: models.Season, weeks: list[dict[str, Any]]) -> tuple[int, int]:
    """Upsert the weeks of a season; returns (created, stale).

    The weeks are updated one by one, so moving the calendar (every week shifted by a day)
    goes through states where two weeks overlap. `weeks_no_overlap` is deferred for the
    duration and set back to immediate at the end, which checks the final state right here
    instead of leaving a surprise for the caller's commit.
    """
    await session.execute(text("SET CONSTRAINTS weeks_no_overlap DEFERRED"))
    existing = {
        week.number: week
        for week in (await session.execute(select(models.Week).where(models.Week.season_id == season.id))).scalars()
    }
    created = 0
    for item in weeks:
        number = int(_required(item, "num", "week"))
        where = f"week {number}"
        week = existing.get(number)
        if week is None:
            week = models.Week(season_id=season.id, number=number)
            session.add(week)
            created += 1
        week.title = _required(item, "title", where)
        week.starts_on = _as_date(item, "start", where)
        week.ends_on = _as_date(item, "end", where)
        week.intro = _text(item, "intro")
        week.task_min = _required(item, "minimum", where)
        week.task_max = _text(item, "maximum")
        week.word = _text(item, "word")
        week.word_ru = _text(item, "word_ru")
        week.word_meaning = _text(item, "word_meaning")
    await session.flush()
    await session.execute(text("SET CONSTRAINTS weeks_no_overlap IMMEDIATE"))
    numbers = {int(_required(item, "num", "week")) for item in weeks}
    return created, len([number for number in existing if number not in numbers])


async def _import_achievement_types(
    session: AsyncSession, season: models.Season, achievements: list[dict[str, Any]]
) -> tuple[int, int]:
    """Upsert the achievement catalogue of a season; returns (created, stale)."""
    existing = {
        row.code: row
        for row in (
            await session.execute(select(models.AchievementType).where(models.AchievementType.season_id == season.id))
        ).scalars()
    }
    created = 0
    for index, item in enumerate(achievements):
        code = _required(item, "code", "achievement")
        row = existing.get(code)
        if row is None:
            row = models.AchievementType(season_id=season.id, code=code)
            session.add(row)
            created += 1
        row.emoji = _text(item, "emoji")
        row.name = _required(item, "name", f"achievement '{code}'")
        row.description = _text(item, "for")
        row.sort = int(item.get("index", index))
    codes = {_required(item, "code", "achievement") for item in achievements}
    return created, len([code for code in existing if code not in codes])
