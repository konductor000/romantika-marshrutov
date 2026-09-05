"""The season journal as a printable document (ARCHITECTURE §10, DOMAIN §7).

One Jinja template → HTML → WeasyPrint → PDF. The same `JournalView` feeds the bot and the
Mini App, so the PDF cannot say something they do not. The document reads like a travel
journal: a title page with the passport spread, then one section per stamped week with what
the participant wrote and shot that week, then the dictionary, the facts and Mila's word.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from romantika.domain.types import Level, StampLevel
from romantika.services.journal import JournalView, JournalWeek

TEMPLATES = Path(__file__).resolve().parent / "templates"
LEVEL_NAMES = {Level.RESIDENT: "Резидент", Level.TRAVELER: "Путешественник", Level.TOURIST: "Турист"}
LEVEL_NOTES = {
    Level.RESIDENT: "девять штампов и больше — сезон прожит целиком",
    Level.TRAVELER: "четыре штампа и больше — больше половины пути",
    Level.TOURIST: "первый штамп — путь начат",
}
#: Photos per week and per journal: enough to remember the week by, small enough to send in a chat.
MAX_PHOTOS_PER_WEEK = 6
MAX_PHOTOS = 36
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip

_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def date_words(day: date, *, year: bool = False) -> str:
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    return f"{text} {day.year}" if year else text


def span_words(start: date | None, end: date | None) -> str:
    """«31 августа — 6 сентября» (the month named once when it is the same)."""
    if start is None or end is None:
        return ""
    if start.month == end.month:
        return f"{start.day}—{end.day} {MONTHS_GENITIVE[end.month - 1]}"
    return f"{date_words(start)} — {date_words(end)}"


@dataclass(frozen=True, slots=True)
class WeekCard:
    number: int
    title: str
    star: bool
    dates: str
    texts: list[str]
    photos: list[str]
    files_more: int
    """Files the section does not show: non-images and photos past the cap."""


def _photos_of(week: JournalWeek, media_root: Path | None, budget: int) -> tuple[list[str], int]:
    """File URIs of the week's photos within the budget, and how many files stayed out."""
    photos: list[str] = []
    skipped = 0
    for item in week.media:
        if media_root is None:
            skipped += 1
            continue
        path = media_root / item.path
        if not (item.downloaded and path.suffix.lower() in IMAGE_SUFFIXES and path.exists()):
            skipped += 1
            continue
        if len(photos) >= min(MAX_PHOTOS_PER_WEEK, budget):
            skipped += 1
            continue
        photos.append(path.resolve().as_uri())
    return photos, skipped


def render_journal_html(view: JournalView, *, media_root: Path | None = None, level: Level | None = None) -> str:
    """The journal as HTML. Photos are embedded only when `media_root` says where they are."""
    budget = MAX_PHOTOS
    cards: list[WeekCard] = []
    for week in view.weeks:
        photos, skipped = _photos_of(week, media_root, budget)
        budget -= len(photos)
        cards.append(
            WeekCard(
                number=week.number,
                title=week.title,
                star=week.level is StampLevel.MAX,
                dates=span_words(week.starts_on, week.ends_on),
                texts=[text[:1500] for text in week.texts],
                photos=photos,
                files_more=skipped,
            )
        )
    stamped: dict[int, JournalWeek] = {week.number: week for week in view.weeks}
    grid = []
    for number in range(1, view.weeks_total + 1):
        entry = stamped.get(number)
        mark = "★" if entry and entry.level is StampLevel.MAX else ("✓" if entry else "")
        grid.append(
            {
                "number": number,
                "mark": mark,
                "title": entry.title if entry else "",
                "state": "star" if mark == "★" else "ok" if mark else "empty",
            }
        )
    name = view.user.display_name if view.user else ""
    template = _env.get_template("journal.html")
    return template.render(
        view=view,
        name=name,
        cards=cards,
        grid=grid,
        level_name=LEVEL_NAMES.get(level) if level else None,
        level_note=LEVEL_NOTES.get(level) if level else None,
        season=view.season,
        starts=date_words(view.season.starts_on),
        ends=date_words(view.season.ends_on, year=True),
        stars=sum(1 for week in view.weeks if week.level is StampLevel.MAX),
        photos_total=sum(len(card.photos) for card in cards),
    )


def render_journal_pdf(view: JournalView, *, media_root: Path | None = None, level: Level | None = None) -> bytes:
    from weasyprint import HTML  # heavy import; only the worker needs it

    html = render_journal_html(view, media_root=media_root, level=level)
    document = HTML(string=html, base_url=str(media_root or TEMPLATES))
    result: bytes = document.write_pdf()
    return result
