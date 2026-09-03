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
