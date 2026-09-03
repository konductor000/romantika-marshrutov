"""The season journal as a printable document (ARCHITECTURE §10, DOMAIN §7).

One Jinja template → HTML → WeasyPrint → PDF. The same `JournalView` feeds the bot and the
Mini App, so the PDF cannot say something they do not.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from romantika.domain.types import Level, StampLevel
from romantika.services.journal import JournalView

TEMPLATES = Path(__file__).resolve().parent / "templates"
LEVEL_NAMES = {Level.RESIDENT: "Резидент", Level.TRAVELER: "Путешественник", Level.TOURIST: "Турист"}
MAX_PHOTOS = 12
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def _month_genitive(day_month: int) -> str:
    return [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ][day_month - 1]  # fmt: skip


def render_journal_html(view: JournalView, *, media_root: Path | None = None, level: Level | None = None) -> str:
    """The journal as HTML. Photos are embedded only when `media_root` says where they are."""
    photos: list[str] = []
    if media_root is not None:
        for item in view.media:
            path = media_root / item.path
            if item.downloaded and path.suffix.lower() in IMAGE_SUFFIXES and path.exists():
                photos.append(path.resolve().as_uri())
            if len(photos) >= MAX_PHOTOS:
                break
    stamped = {week.number: week for week in view.weeks}
    grid = []
    for number in range(1, view.weeks_total + 1):
        week = stamped.get(number)
        mark = "★" if week and week.level is StampLevel.MAX else ("✓" if week else "·")
        grid.append({"number": number, "mark": mark, "title": week.title if week else ""})
    name = view.user.display_name if view.user else ""
    template = _env.get_template("journal.html")
    return template.render(
        view=view,
        name=name,
        photos=photos,
        grid=grid,
        level_name=LEVEL_NAMES.get(level) if level else None,
        season=view.season,
        ends=f"{view.season.ends_on.day} {_month_genitive(view.season.ends_on.month)} {view.season.ends_on.year}",
        starts=f"{view.season.starts_on.day} {_month_genitive(view.season.starts_on.month)}",
        stars=sum(1 for week in view.weeks if week.level is StampLevel.MAX),
    )


def render_journal_pdf(view: JournalView, *, media_root: Path | None = None, level: Level | None = None) -> bytes:
    from weasyprint import HTML  # heavy import; only the worker needs it

    html = render_journal_html(view, media_root=media_root, level=level)
    document = HTML(string=html, base_url=str(media_root or TEMPLATES))
    result: bytes = document.write_pdf()
    return result
