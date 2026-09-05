"""Request and response bodies of the JSON API (ARCHITECTURE §8.1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Me(BaseModel):
    id: int
    first_name: str | None
    username: str | None
    is_admin: bool


class SeasonOut(BaseModel):
    id: int
    slug: str
    title: str
    title_accusative: str
    starts_on: date
    ends_on: date
    daily_kind: str | None
    daily_note: str


class PassportOut(BaseModel):
    stamps: int
    stamps_max: int
    weeks_total: int
    freezes_used: int
    freezes_left: int
    freezes_total: int
    best_streak: int
    current_streak: int
    level: str | None
    freeze_reasons: list[str] = Field(default_factory=list)


class WeekOut(BaseModel):
    id: int
    number: int
    title: str
    state: str
    level: str | None = None
    starts_on: date
    ends_on: date
    intro: str = ""
    task_min: str = ""
    task_max: str = ""
    word: str = ""
    word_ru: str = ""
    word_meaning: str = ""


class MediaOut(BaseModel):
    id: str
    url: str
    mime: str | None
    downloaded: bool


class ReportOut(BaseModel):
    id: int
    week_number: int | None
    kind: str
    level: str
    text: str | None
    created_at: datetime
    media: list[MediaOut]
    edited_at: datetime | None = None
    editable: bool = False
    """True while the report's week is open: text and files may still be changed (DOMAIN §2)."""


class WordOut(BaseModel):
    word: str
    meaning: str
    week_number: int | None = None


class JournalOut(BaseModel):
    season: SeasonOut
    user: Me
    passport: PassportOut
    weeks: list[WeekOut]
    reports: list[ReportOut]
    achievements: list[str]
    words: list[WordOut]
    season_words: list[WordOut]
    facts: list[str]
    wish: str | None


class JobOut(BaseModel):
    job_id: int
    status: str
    url: str | None = None
    error: str | None = None


class SessionIn(BaseModel):
    init_data: str


# --- admin ----------------------------------------------------------------------


class WeekEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    intro: str | None = None
    task_min: str | None = None
    task_max: str | None = None
    word: str | None = None
    word_ru: str | None = None
    word_meaning: str | None = None


class AdminWeekOut(WeekOut):
    pass


class ParticipantOut(BaseModel):
    id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    joined_at: datetime
    stamps: int
    stamps_max: int
    level: str | None
    freezes_left: int
    freezes_total: int
    best_streak: int
    current_streak: int
    week_intent: Literal["take", "try", "skip"] | None = None
    """«Берусь / Попробую / Мимо» on the week running now; the people filters read it."""
    week_level: Literal["min", "max"] | None = None
    """The stamp on the week running now, if any."""


class ParticipantDetail(BaseModel):
    user: ParticipantOut
    passport: PassportOut
    weeks: list[WeekOut]
    achievements: list[str]
    wish: str | None
    reports: list[ReportOut]
    words: list[WordOut]


class StampSet(BaseModel):
    level: Literal["min", "max"] | None


class StampOut(BaseModel):
    level: str | None


class FreezeGrant(BaseModel):
    reason: Literal["comment", "meetup", "friend", "manual"]
    note: str | None = None


class FreezeOut(BaseModel):
    granted: bool
    freezes_total: int


class AchievementGrant(BaseModel):
    code_or_text: str = Field(min_length=1, max_length=64)


class AchievementOut(BaseModel):
    code: str
    label: str
    created: bool


class WishSet(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class FactCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    week_number: int | None = None


class FactOut(BaseModel):
    id: int
    text: str
    author_id: int | None
    author_name: str | None
    week_id: int | None
    created_at: datetime


class SubmittedOut(BaseModel):
    user_id: int
    name: str
    level: str


class SummaryOut(BaseModel):
    week_number: int
    week_title: str
    members_total: int
    reports_total: int
    took: list[int]
    took_names: list[str]
    submitted: list[SubmittedOut]
    took_not_submitted: list[int]
    took_not_submitted_names: list[str]
    core_best: int
    core_current: int
    draft_post: str


class AuditOut(BaseModel):
    id: int
    actor_id: int | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    created_at: datetime


class AchievementTypeOut(BaseModel):
    code: str
    emoji: str
    name: str
    description: str
    label: str


# --- the participant Mini App (ARCHITECTURE §8.1) --------------------------------


class TzolkinOut(BaseModel):
    number: int
    kin: int
    sign_name: str
    sign_symbol: str
    sign_emoji: str
    short: str
    day_advice: str


class WeekWordOut(BaseModel):
    week_number: int
    title: str = ""
    word: str
    word_ru: str = ""
    meaning: str = ""


class TodayOut(BaseModel):
    date: date
    tzolkin: TzolkinOut | None
    word: WeekWordOut | None
    memory: WeekWordOut | None
    note: str
    calendar_url: str | None


class CurrentWeekOut(WeekOut):
    intent: Literal["take", "try", "skip"] | None = None
    reports_count: int = 0
    deadline: str = ""


class TextsOut(BaseModel):
    """Bot texts the app shows verbatim (HTML with <b>/<i> only), so the two never drift."""

    greeting: str
    help: str
    end_of_season: str
    write_prompt: str
    word_prompt: str
    fact_prompt: str
    journal_now: str


class LinksOut(BaseModel):
    channel_url: str | None
    bot_username: str | None
    admin_app: bool


class HomeOut(BaseModel):
    season: SeasonOut
    user: Me
    today: TodayOut
    week: CurrentWeekOut | None
    next_week_starts_on: date | None
    passport: PassportOut
    weeks: list[WeekOut]
    achievements: list[str]
    wish: str | None
    texts: TextsOut
    links: LinksOut


class IntentIn(BaseModel):
    week_number: int
    choice: Literal["take", "try", "skip"]


class IntentOut(BaseModel):
    choice: str
    hint: str


class ReportResult(BaseModel):
    report_id: int
    week_number: int | None
    out_of_week: bool
    level: str
    stamp_level: str | None
    freeze_granted: bool
    message: str


class LevelIn(BaseModel):
    level: Literal["min", "max"]


class LevelOut(BaseModel):
    ok: bool
    stamp_level: str | None
    message: str


class CancelOut(BaseModel):
    ok: bool
    stamp_level: str | None
    message: str


class ReportEditOut(BaseModel):
    report: ReportOut
    stamp_level: str | None
    freeze_granted: bool
    message: str


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    message: str


class WordAdded(BaseModel):
    word: str
    meaning: str
    freeze_granted: bool
    message: str


class UserWordOut(BaseModel):
    id: int
    word: str
    meaning: str
    author: str
    mine: bool


class DictionaryOut(BaseModel):
    week_words: list[WeekWordOut]
    user_words: list[UserWordOut]
    about: str


class FactItem(BaseModel):
    id: int
    text: str
    author: str | None
    mine: bool
    created_at: datetime


class FactsOut(BaseModel):
    about: str
    facts: list[FactItem]


# --- admin extras -----------------------------------------------------------------


class RemindersOut(BaseModel):
    enabled: bool


class RemindIn(BaseModel):
    week_number: int | None = None
    """The week Mila is looking at; None means the week running now."""


class LetterOut(BaseModel):
    id: int
    user_id: int
    author: str
    source: Literal["bot", "app", "out_of_week", "not_report"]
    text: str
    created_at: datetime
    reply_text: str | None
    replied_at: datetime | None
    report_id: int | None


class LettersOut(BaseModel):
    unanswered: int
    letters: list[LetterOut]


class RemindersIn(BaseModel):
    enabled: bool


class QueuedOut(BaseModel):
    job_id: int
    status: str = "queued"
