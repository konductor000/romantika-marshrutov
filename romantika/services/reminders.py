"""Reminders to people who took the week and stayed silent (DOMAIN §8).

Used by the bot (`/remind`, the panel button) and by the worker scheduler. The texts are
the legacy ones; who gets them is decided by `summary.reminder_recipients`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from romantika.services import content, summary

logger = logging.getLogger(__name__)

SETTING_KEY = "reminders_enabled"


class MessageSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReminderResult:
    sent: int
    total: int
    week_title: str | None

    def describe(self) -> str:
        if self.week_title is None:
            return "Сейчас неделя сезона не идёт."
        if self.total == 0:
            return "Напоминать некому: все, кто взялся, уже прислали."
        return f"Напоминание ушло: {self.sent} из {self.total}"


async def enabled(session: AsyncSession) -> bool:
    value = await content.get_setting(session, SETTING_KEY, "on")
    return value not in ("off", "выкл", "0", "false")


async def set_enabled(session: AsyncSession, value: bool) -> None:
    await content.set_setting(session, SETTING_KEY, "on" if value else "off")


async def send(
    session: AsyncSession,
    *,
    season_id: int,
    week_number: int | None,
    telegram: MessageSender,
    text_for: Callable[[str], str] | None = None,
    now: datetime,
) -> ReminderResult:
    """Send one reminder to every recipient of the week; a failed delivery is counted, not raised."""
    from romantika.domain.calendar import to_moscow
    from romantika.texts import ru

    week = (
        await content.week_by_number(session, season_id, week_number)
        if week_number is not None
        else await content.current_week(session, season_id, today=to_moscow(now).date())
    )
    if week is None:
        return ReminderResult(sent=0, total=0, week_title=None)
    recipients = await summary.reminder_recipients(session, season_id=season_id, week_number=week.number)
    text = (text_for or ru.reminder_thursday)(week.title)
    sent = 0
    for user_id in recipients:
        try:
            await telegram.send_message(user_id, text)
            sent += 1
        except Exception as exc:
            logger.warning("reminder_not_delivered", extra={"user_id": user_id, "error": str(exc)})
    return ReminderResult(sent=sent, total=len(recipients), week_title=week.title)


async def mark_sent(session: AsyncSession, key: str, *, now: datetime) -> bool:
    """Claim a reminder slot (`YYYY-MM-DD:<slug>`); False when it was already claimed today."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from romantika.db import models

    statement = (
        pg_insert(models.ReminderLog)
        .values(key=key, sent_at=now, recipients=0, created_at=now)
        .on_conflict_do_nothing(index_elements=[models.ReminderLog.key])
    )
    result = await session.execute(statement)
    affected = getattr(result, "rowcount", 0)
    return bool(affected)


async def record_recipients(session: AsyncSession, key: str, recipients: int) -> None:
    from romantika.db import models

    row = await session.get(models.ReminderLog, key)
    if row is not None:
        row.recipients = recipients
        await session.flush()
