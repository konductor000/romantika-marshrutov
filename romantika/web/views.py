"""Assembling API responses from service view models (no business logic here)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from romantika.domain.types import WeekState
from romantika.services import freezes, journal, passport, people
from romantika.services.content import SeasonDTO, WeekDTO
from romantika.services.passport import PassportView
from romantika.web import schemas


def season_out(season: SeasonDTO) -> schemas.SeasonOut:
    return schemas.SeasonOut(
        id=season.id,
        slug=season.slug,
        title=season.title,
        title_accusative=season.title_accusative,
        starts_on=season.starts_on,
        ends_on=season.ends_on,
        daily_kind=season.daily_kind,
        daily_note=season.daily_note,
    )


def passport_out(view: PassportView, reasons: list[str]) -> schemas.PassportOut:
    b = view.breakdown
    return schemas.PassportOut(
        stamps=b.stamps,
        stamps_max=view.stamps_max,
        weeks_total=view.weeks_total,
        freezes_used=b.freezes_used,
        freezes_left=b.freezes_left,
        freezes_total=b.freezes_total,
        best_streak=b.best_streak,
        current_streak=b.current_streak,
        level=view.level.value if view.level else None,
        freeze_reasons=reasons,
    )


def week_out(week: WeekDTO, state: WeekState, level: str | None, *, reveal: bool) -> schemas.WeekOut:
    """Future weeks travel with their calendar only: no task texts before the week starts."""
    base = schemas.WeekOut(
        id=week.id,
        number=week.number,
        title=week.title if reveal else f"Неделя {week.number}",
        state=state.value,
        level=level,
        starts_on=week.starts_on,
        ends_on=week.ends_on,
    )
    if not reveal:
        return base
    return base.model_copy(
        update={
            "intro": week.intro,
            "task_min": week.task_min,
            "task_max": week.task_max,
            "word": week.word,
            "word_ru": week.word_ru,
            "word_meaning": week.word_meaning,
        }
    )


def weeks_out(view: PassportView, *, today: date, reveal_all: bool = False) -> list[schemas.WeekOut]:
    result = []
    for week in view.weeks:
        state = view.breakdown.states.get(week.number, WeekState.LOCKED)
        level = view.stamps.get(week.number)
        reveal = reveal_all or week.starts_on <= today
        result.append(week_out(week, state, level.value if level else None, reveal=reveal))
    return result


async def journal_out(
    session: AsyncSession, *, season: SeasonDTO, user_id: int, today: date, principal_admin: bool
) -> schemas.JournalOut:
    view = await passport.build(session, season_id=season.id, user_id=user_id, today=today)
    jview = await journal.build(session, season_id=season.id, user_id=user_id, today=today)
    reasons = await freezes.reasons(session, season.id, user_id)
    reports = await journal.reports_for_user(session, season_id=season.id, user_id=user_id)
    user = await people.get_user(session, user_id)
    assert user is not None
    return schemas.JournalOut(
        season=season_out(season),
        user=schemas.Me(id=user.id, first_name=user.first_name, username=user.username, is_admin=principal_admin),
        passport=passport_out(view, reasons),
        weeks=weeks_out(view, today=today),
        reports=[
            schemas.ReportOut(
                id=r.id,
                week_number=r.week_number,
                kind=r.kind,
                level=r.level,
                text=r.text,
                created_at=r.created_at,
                media=[
                    schemas.MediaOut(
                        id=str(m.media_id), url=f"/media/{m.media_id}", mime=m.mime, downloaded=m.downloaded
                    )
                    for m in r.media
                ],
            )
            for r in reports
        ],
        achievements=jview.achievements,
        words=[schemas.WordOut(word=w.word, meaning=w.meaning) for w in jview.words],
        season_words=[
            schemas.WordOut(word=w.word, meaning=w.meaning, week_number=w.number) for w in jview.season_words
        ],
        facts=[f.text for f in jview.facts],
        wish=jview.wish,
    )
