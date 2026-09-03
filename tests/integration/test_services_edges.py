"""Edge cases of the services layer that the acceptance suite does not pin down.

Cancel semantics (DOMAIN §2), the freeze ceiling (§3), the dialog TTL (§10.8), the job
retry ladder and the idempotency of the media download.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from romantika.config import DATA_DIR
from romantika.db import models
from romantika.domain.types import ReportKind, StampLevel
from romantika.services import (
    achievements,
    content,
    facts,
    freezes,
    jobs,
    people,
    reports,
    seed,
    stamps,
    summary,
    words,
)
from romantika.services.gateways import TelegramFile
from romantika.services.media import MediaStore
from romantika.services.people import TelegramUser
from romantika.services.reports import IncomingFile, IncomingMessage

SEASON_JSON = DATA_DIR / "seasons" / "mexico-2026.json"
ADMIN_ID = 355363829
ALICE = 1001
BOB = 1002


def moscow(year: int, month: int, day: int, hour: int = 12) -> datetime:
    """An aware UTC datetime that is `hour` o'clock in Moscow on that day."""
    return datetime(year, month, day, hour, 0, tzinfo=UTC) - timedelta(hours=3)


@dataclass
class FakeTelegram:
    payload: bytes = b"fake-jpeg-bytes"
    calls: list[str] = field(default_factory=list)

    async def get_file(self, file_id: str) -> TelegramFile:
        return TelegramFile(file_path=f"photos/{file_id}.jpg", file_size=len(self.payload))

    async def download_file(self, file_path: str, destination: Path) -> None:
        self.calls.append(file_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)


@pytest.fixture
async def season(db_session: AsyncSession) -> int:
    result = await seed.import_season(db_session, SEASON_JSON)
    await content.activate_season(db_session, result.season_id, actor_id=ADMIN_ID)
    for user_id, name in ((ADMIN_ID, "Мила"), (ALICE, "Алиса"), (BOB, "Боб")):
        await people.upsert_user(
            db_session,
            TelegramUser(id=user_id, username=None, first_name=name, last_name=None),
            now=moscow(2026, 8, 20),
        )
        await people.ensure_member(db_session, result.season_id, user_id, now=moscow(2026, 8, 20))
    return result.season_id


def photo(msg_id: int = 1, caption: str | None = None, file_id: str = "AgACAgIAAxkBAAI") -> IncomingMessage:
    return IncomingMessage(
        kind=ReportKind.PHOTO,
        text=caption,
        tg_chat_id=ALICE,
        tg_message_id=msg_id,
        files=[IncomingFile(kind=ReportKind.PHOTO, file_id=file_id, file_unique_id=f"u-{file_id}", mime="image/jpeg")],
    )


def text(body: str, msg_id: int = 1) -> IncomingMessage:
    return IncomingMessage(kind=ReportKind.TEXT, text=body, tg_chat_id=ALICE, tg_message_id=msg_id, files=[])


# --- reports and stamps ----------------------------------------------------------


async def test_voice_is_a_minimum_report(db_session: AsyncSession, season: int) -> None:
    """Legacy ignored voice messages; in v2 they are a report (DOMAIN §10.3)."""
    message = IncomingMessage(
        kind=ReportKind.VOICE,
        tg_chat_id=ALICE,
        tg_message_id=1,
        files=[IncomingFile(kind=ReportKind.VOICE, file_id="voice-1", mime="audio/ogg")],
    )
    result = await reports.accept(db_session, season_id=season, user_id=ALICE, message=message, now=moscow(2026, 9, 2))
    assert result.level is StampLevel.MIN and result.stamp_level is StampLevel.MIN
    row = await db_session.get(models.Media, result.media_ids[0])
    assert row is not None and row.path.endswith(".ogg")


async def test_cancel_twice_is_refused_and_keeps_the_stamp(db_session: AsyncSession, season: int) -> None:
    first = await reports.accept(db_session, season_id=season, user_id=ALICE, message=photo(), now=moscow(2026, 9, 2))
    second = await reports.accept(
        db_session, season_id=season, user_id=ALICE, message=photo(msg_id=2), now=moscow(2026, 9, 3)
    )
    assert (await reports.cancel(db_session, user_id=ALICE, report_id=first.report_id, now=moscow(2026, 9, 4))).ok
    again = await reports.cancel(db_session, user_id=ALICE, report_id=first.report_id, now=moscow(2026, 9, 4))
    assert again.ok is False and again.reason == "already_cancelled"
    assert await stamps.get_level(db_session, user_id=ALICE, week_id=(await _week(db_session, season, 1)).id) is (
        StampLevel.MAX
    ), "the other photo still holds the maximum"
    assert second.stamp_level is StampLevel.MAX


async def test_cancel_leaves_an_admin_stamp_alone(db_session: AsyncSession, season: int) -> None:
    """«Штамп, выставленный Милой вручную, отменой отчётов не трогается» (DOMAIN §2)."""
    accepted = await reports.accept(
        db_session, season_id=season, user_id=ALICE, message=text("минимум"), now=moscow(2026, 9, 2)
    )
    await stamps.admin_set(
        db_session,
        actor_id=ADMIN_ID,
        season_id=season,
        user_id=ALICE,
        week_number=1,
        level=StampLevel.MAX,
        now=moscow(2026, 9, 3),
    )
    cancelled = await reports.cancel(db_session, user_id=ALICE, report_id=accepted.report_id, now=moscow(2026, 9, 4))
    assert cancelled.ok is True and cancelled.stamp_level is StampLevel.MAX


async def test_cancel_of_an_out_of_week_letter(db_session: AsyncSession, season: int) -> None:
    letter = await reports.accept(
        db_session, season_id=season, user_id=ALICE, message=text("до сезона"), now=moscow(2026, 8, 25)
    )
    cancelled = await reports.cancel(db_session, user_id=ALICE, report_id=letter.report_id, now=moscow(2026, 8, 25))
    assert cancelled.ok is True and cancelled.stamp_level is None


async def test_fix_level_of_an_unknown_week(db_session: AsyncSession, season: int) -> None:
    fix = await reports.fix_level(
        db_session, season_id=season, user_id=ALICE, week_number=99, level=StampLevel.MAX, now=moscow(2026, 9, 3)
    )
    assert fix.ok is False and fix.reason == "no_week"


# --- freezes ----------------------------------------------------------------------


async def test_manual_freezes_repeat_but_stop_at_the_ceiling(db_session: AsyncSession, season: int) -> None:
    """Only `word` and `max` are once-per-season; the ceiling is 2 base + 3 earned."""
    now = moscow(2026, 9, 3)
    granted = [
        await freezes.grant(
            db_session,
            season_id=season,
            user_id=BOB,
            reason=models.FreezeReason.MANUAL,
            granted_by=ADMIN_ID,
            now=now,
            note=f"#{index}",
        )
        for index in range(4)
    ]
    assert granted == [True, True, True, False]
    assert await freezes.bonus_count(db_session, season, BOB) == 3
    assert await freezes.total(db_session, season, BOB) == 5


async def test_first_word_freeze_is_granted_once(db_session: AsyncSession, season: int) -> None:
    now = moscow(2026, 9, 3)
    first = await words.add(db_session, season_id=season, user_id=BOB, week_id=None, raw="tianguis — рынок", now=now)
    second = await words.add(db_session, season_id=season, user_id=BOB, week_id=None, raw="mole — соус", now=now)
    assert (first.freeze_granted, second.freeze_granted) == (True, False)
    assert await freezes.bonus_count(db_session, season, BOB) == 1


# --- dialog state -----------------------------------------------------------------


async def test_dialog_state_lives_exactly_six_hours(db_session: AsyncSession, season: int) -> None:
    start = moscow(2026, 9, 3, 10)
    await people.set_dialog_state(db_session, ALICE, "fact", {"week": 1}, now=start)
    on_the_edge = await people.get_dialog_state(db_session, ALICE, now=start + people.DIALOG_TTL)
    assert on_the_edge is not None and on_the_edge.payload == {"week": 1}
    stale = start + people.DIALOG_TTL + timedelta(seconds=1)
    assert await people.get_dialog_state(db_session, ALICE, now=stale) is None
    assert await people.get_dialog_state(db_session, ALICE, now=start) is None, "an expired state is dropped"


# --- content ----------------------------------------------------------------------


async def test_update_week_refuses_fields_outside_the_whitelist(db_session: AsyncSession, season: int) -> None:
    week = await _week(db_session, season, 1)
    with pytest.raises(ValueError, match="not editable"):
        await content.update_week(db_session, actor_id=ADMIN_ID, week_id=week.id, changes={"starts_on": "2026-01-01"})
    unchanged = await content.update_week(db_session, actor_id=ADMIN_ID, week_id=week.id, changes={"title": week.title})
    assert unchanged.title == week.title
    audited = await _audit_rows(db_session, "week")
    assert audited == 0, "a change that changes nothing is not worth an audit row"


async def test_settings_round_trip(db_session: AsyncSession, season: int) -> None:
    assert await content.get_setting(db_session, "reminders", "on") == "on"
    await content.set_setting(db_session, "reminders", "off")
    assert await content.get_setting(db_session, "reminders") == "off"


# --- achievements and facts -------------------------------------------------------


async def test_free_text_achievement_is_trimmed_to_the_code_column(db_session: AsyncSession, season: int) -> None:
    long_text = "Самый ранний отчёт " * 10
    award = await achievements.award(
        db_session, season_id=season, user_id=ALICE, code_or_text=long_text, awarded_by=ADMIN_ID, now=moscow(2026, 9, 3)
    )
    assert award.created is True
    assert len(award.code) == achievements.CODE_LENGTH
    assert award.label == long_text.strip()


async def test_removed_fact_leaves_the_row_and_an_audit_trail(db_session: AsyncSession, season: int) -> None:
    now = moscow(2026, 9, 3)
    fact_id = await facts.add(db_session, season_id=season, week_id=None, text="Мешика", author_id=None, now=now)
    assert await facts.remove(db_session, fact_id=fact_id, actor_id=ADMIN_ID, now=now) is True
    row = await db_session.get(models.Fact, fact_id)
    assert row is not None and row.deleted_at == now
    audited = await _audit_rows(db_session, "fact")
    assert audited == 1


# --- media ------------------------------------------------------------------------


async def test_media_download_repeats_when_the_file_is_gone(
    db_session: AsyncSession, season: int, tmp_path: Path
) -> None:
    """The row says «downloaded», the disk says otherwise: we fetch it again."""
    store = MediaStore(tmp_path)
    telegram = FakeTelegram()
    accepted = await reports.accept(
        db_session, season_id=season, user_id=ALICE, message=photo(), now=moscow(2026, 9, 2)
    )
    first = await store.download(db_session, accepted.media_ids[0], telegram, now=moscow(2026, 9, 2))
    (tmp_path / first.path).unlink()
    again = await store.download(db_session, accepted.media_ids[0], telegram, now=moscow(2026, 9, 3))
    assert again.path == first.path and len(telegram.calls) == 2
    assert not list(tmp_path.rglob("*.part")), "the part file is renamed, never left behind"


# --- summary ----------------------------------------------------------------------


async def test_week_summary_counts_the_core_both_ways(db_session: AsyncSession, season: int) -> None:
    for week_number, day in ((1, moscow(2026, 9, 2)), (2, moscow(2026, 9, 9))):
        assert week_number
        await reports.accept(db_session, season_id=season, user_id=ALICE, message=photo(msg_id=week_number), now=day)
    # Bob keeps a stamp only in week 1, so his current streak breaks and his best one stays.
    await reports.accept(db_session, season_id=season, user_id=BOB, message=text("минимум", 3), now=moscow(2026, 9, 2))

    view = await summary.week(db_session, season_id=season, week_number=2, today=date(2026, 9, 23))
    assert view.week_title == "Красками"
    assert view.core_best == 1 and view.core_current == 1
    core = await summary.core(db_session, season_id=season, today=date(2026, 9, 23))
    assert core.best == [ALICE] and core.current == [ALICE]


async def test_draft_post_mentions_quotes_word_and_the_silent_ones(db_session: AsyncSession, season: int) -> None:
    week = await _week(db_session, season, 1)
    await people.set_intent(
        db_session,
        season_id=season,
        user_id=BOB,
        week_id=week.id,
        choice=models.IntentChoice.TAKE,
        now=moscow(2026, 9, 1),
    )
    await reports.accept(
        db_session, season_id=season, user_id=ALICE, message=photo(caption="тако удались"), now=moscow(2026, 9, 2)
    )
    post = await summary.draft_post(db_session, season_id=season, week_number=1, today=date(2026, 9, 7))
    assert "Черновик «Привала» · неделя 1 · За столом" in post
    assert "⭐ Алиса — тако удались" in post
    assert "Слово недели: antojo" in post
    assert "#маршрут_итоги #мексика" in post
    assert "взялись и не прислали — Боб" in post


# --- jobs -------------------------------------------------------------------------


async def test_job_fails_after_five_attempts(db_session: AsyncSession) -> None:
    now = moscow(2026, 9, 3)
    job_id = await jobs.enqueue(db_session, "media_download", {"media_id": "x"}, now=now)
    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        row = await db_session.get(models.Job, job_id)
        assert row is not None
        claimed = await jobs.claim(db_session, now=row.run_after)
        assert claimed is not None and claimed.attempts == attempt - 1
        await jobs.finish(db_session, job_id, error="boom", now=row.run_after)

    row = await db_session.get(models.Job, job_id)
    assert row is not None and row.status == models.JobStatus.FAILED.value
    assert row.attempts == jobs.MAX_ATTEMPTS and row.finished_at is not None
    assert await jobs.claim(db_session, now=now + timedelta(days=1)) is None, "a failed job is not retried"


async def test_enqueue_can_delay_a_job(db_session: AsyncSession) -> None:
    now = moscow(2026, 9, 3)
    await jobs.enqueue(db_session, "remind", {}, now=now, run_after=now + timedelta(hours=2))
    assert await jobs.claim(db_session, now=now) is None
    claimed = await jobs.claim(db_session, now=now + timedelta(hours=2))
    assert claimed is not None and claimed.kind == "remind"


async def _audit_rows(session: AsyncSession, entity: str) -> int:
    query = select(func.count()).select_from(models.AuditLog).where(models.AuditLog.entity == entity)
    return int((await session.execute(query)).scalar_one())


async def _week(session: AsyncSession, season_id: int, number: int) -> content.WeekDTO:
    week = await content.week_by_number(session, season_id, number)
    assert week is not None
    return week
