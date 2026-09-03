"""Import a season description (`data/seasons/*.json`) into the database.

Idempotent: rerunning updates the rows in place, so content fixes can be re-imported.
Like every service, it flushes but never commits — the caller owns the transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models


@dataclass(frozen=True, slots=True)
class SeedResult:
    """What one import did, for the CLI output and tests."""

    season_id: int
    slug: str
    created: bool
    weeks: int
    weeks_created: int
    achievement_types: int
    achievement_types_created: int


def _as_date(value: str) -> date:
    return date.fromisoformat(value)


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return "" if value is None else str(value)


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

    season.title = _text(payload, "season")
    season.title_accusative = _text(payload, "season_about")
    season.hashtag = _text(payload, "hashtag")
    season.starts_on = _as_date(payload["start"])
    season.ends_on = _as_date(payload["end"])
    season.daily_kind = daily.get("kind")
    season.daily_title = _text(daily, "title")
    season.daily_note = _text(daily, "note")
    await session.flush()

    weeks_created = await _import_weeks(session, season, payload.get("weeks") or [])
    types_created = await _import_achievement_types(session, season, payload.get("achievements") or [])
    await session.flush()

    return SeedResult(
        season_id=season.id,
        slug=slug,
        created=created,
        weeks=len(payload.get("weeks") or []),
        weeks_created=weeks_created,
        achievement_types=len(payload.get("achievements") or []),
        achievement_types_created=types_created,
    )


async def _import_weeks(session: AsyncSession, season: models.Season, weeks: list[dict[str, Any]]) -> int:
    existing = {
        week.number: week
        for week in (await session.execute(select(models.Week).where(models.Week.season_id == season.id))).scalars()
    }
    created = 0
    for item in weeks:
        number = int(item["num"])
        week = existing.get(number)
        if week is None:
            week = models.Week(season_id=season.id, number=number)
            session.add(week)
            created += 1
        week.title = _text(item, "title")
        week.starts_on = _as_date(item["start"])
        week.ends_on = _as_date(item["end"])
        week.intro = _text(item, "intro")
        week.task_min = _text(item, "minimum")
        week.task_max = _text(item, "maximum")
        week.word = _text(item, "word")
        week.word_ru = _text(item, "word_ru")
        week.word_meaning = _text(item, "word_meaning")
    return created


async def _import_achievement_types(
    session: AsyncSession, season: models.Season, achievements: list[dict[str, Any]]
) -> int:
    existing = {
        row.code: row
        for row in (
            await session.execute(select(models.AchievementType).where(models.AchievementType.season_id == season.id))
        ).scalars()
    }
    created = 0
    for index, item in enumerate(achievements):
        code = str(item["code"])
        row = existing.get(code)
        if row is None:
            row = models.AchievementType(season_id=season.id, code=code)
            session.add(row)
            created += 1
        row.emoji = _text(item, "emoji")
        row.name = _text(item, "name")
        row.description = _text(item, "for")
        row.sort = int(item.get("index", index))
    return created
