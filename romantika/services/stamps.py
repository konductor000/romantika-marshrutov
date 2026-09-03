"""Stamps: one per participant and week, never downgraded by a later report (DOMAIN §2).

The week title is copied into the stamp at award time, so reordering or renaming a week
later does not rewrite anybody's passport.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.db import models
from romantika.domain import rules
from romantika.domain.types import StampLevel
from romantika.services import content


@dataclass(frozen=True, slots=True)
class StampResult:
    """What `merge` did: the level now, the level before, and whether the row is new."""

    level: StampLevel
    previous: StampLevel | None
    created: bool

    @property
    def upgraded_to_max(self) -> bool:
        """The moment that earns the automatic freeze (DOMAIN §3)."""
        return self.level is StampLevel.MAX and self.previous is not StampLevel.MAX


async def _row(session: AsyncSession, *, user_id: int, week_id: int) -> models.Stamp | None:
    query = select(models.Stamp).where(models.Stamp.user_id == user_id, models.Stamp.week_id == week_id)
    return (await session.execute(query)).scalar_one_or_none()


async def get_level(session: AsyncSession, *, user_id: int, week_id: int) -> StampLevel | None:
    row = await _row(session, user_id=user_id, week_id=week_id)
    return None if row is None else StampLevel(row.level)


async def merge(
    session: AsyncSession,
    *,
    season_id: int,
    user_id: int,
    week_id: int,
    week_title: str,
    level: StampLevel,
    now: datetime,
) -> StampResult:
    """Award the stamp or raise its level; a maximum is never lowered back to a minimum."""
    row = await _row(session, user_id=user_id, week_id=week_id)
    if row is None:
        row = models.Stamp(
            season_id=season_id,
            user_id=user_id,
            week_id=week_id,
            level=level.value,
            week_title_snapshot=week_title,
            awarded_at=now,
            source=models.StampSource.REPORT.value,
        )
        session.add(row)
        await session.flush()
        return StampResult(level=level, previous=None, created=True)

    previous = StampLevel(row.level)
    merged = rules.merge_level(previous, level)
    row.level = merged.value
    await session.flush()
    return StampResult(level=merged, previous=previous, created=False)


async def admin_set(
    session: AsyncSession,
    *,
    actor_id: int | None,
    season_id: int,
    user_id: int,
    week_number: int,
    level: StampLevel | None,
    now: datetime,
) -> StampLevel | None:
    """Mila's override for any week, including a downgrade and a removal; audited."""
    week = await content.week_by_number(session, season_id, week_number)
    if week is None:
        raise content.ContentError(f"season {season_id} has no week {week_number}")

    row = await _row(session, user_id=user_id, week_id=week.id)
    before = None if row is None else {"level": row.level, "source": row.source}

    if level is None:
        if row is None:
            return None
        await session.delete(row)
    elif row is None:
        session.add(
            models.Stamp(
                season_id=season_id,
                user_id=user_id,
                week_id=week.id,
                level=level.value,
                week_title_snapshot=week.title,
                awarded_at=now,
                source=models.StampSource.ADMIN.value,
            )
        )
    else:
        row.level = level.value
        row.source = models.StampSource.ADMIN.value
        row.awarded_at = now

    content.audit(
        session,
        actor_id=actor_id,
        action="set" if level is not None else "clear",
        entity="stamp",
        entity_id=f"{user_id}:{week.id}",
        before=before,
        after=None if level is None else {"level": level.value, "source": models.StampSource.ADMIN.value},
    )
    await session.flush()
    return level


async def for_user(session: AsyncSession, *, season_id: int, user_id: int) -> dict[int, StampLevel]:
    """`{week_number: level}` — keyed by number, the way `rules.season_breakdown` wants it."""
    query = (
        select(models.Week.number, models.Stamp.level)
        .join(models.Week, models.Week.id == models.Stamp.week_id)
        .where(models.Stamp.season_id == season_id, models.Stamp.user_id == user_id)
    )
    return {number: StampLevel(level) for number, level in (await session.execute(query)).all()}


async def for_season(session: AsyncSession, season_id: int) -> dict[int, dict[int, StampLevel]]:
    """`{user_id: {week_number: level}}` for the whole season, in one query."""
    query = (
        select(models.Stamp.user_id, models.Week.number, models.Stamp.level)
        .join(models.Week, models.Week.id == models.Stamp.week_id)
        .where(models.Stamp.season_id == season_id)
    )
    result: dict[int, dict[int, StampLevel]] = {}
    for user_id, number, level in (await session.execute(query)).all():
        result.setdefault(user_id, {})[number] = StampLevel(level)
    return result


async def for_week(session: AsyncSession, *, season_id: int, week_id: int) -> dict[int, StampLevel]:
    """`{user_id: level}` of one week, ordered by the moment the stamp was awarded."""
    query = (
        select(models.Stamp.user_id, models.Stamp.level)
        .where(models.Stamp.season_id == season_id, models.Stamp.week_id == week_id)
        .order_by(models.Stamp.awarded_at, models.Stamp.id)
    )
    return {user_id: StampLevel(level) for user_id, level in (await session.execute(query)).all()}
