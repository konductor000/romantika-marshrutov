"""Participant API (ARCHITECTURE §8.1): everything the bot does, for the Mini App.

The rules live in the services; this module only maps HTTP to them and picks the same
Russian texts the bot answers with (`romantika.texts.ru`). Anything that has to reach
Telegram — Mila's copy of a report, the participant's receipt — is queued for the worker
through `services.notify`, never sent from here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse

from romantika.db import models
from romantika.domain.types import ReportKind, StampLevel
from romantika.services import content, facts, jobs, letters, notify, people, reports, words
from romantika.services import media as media_service
from romantika.services.people import TelegramUser
from romantika.services.reports import IncomingFile, IncomingMessage
from romantika.texts import ru
from romantika.web import auth, schemas, views
from romantika.web.deps import (
    MediaStoreDep,
    NowDep,
    Principal,
    PrincipalDep,
    SeasonDep,
    SessionDep,
    SettingsDep,
    TodayDep,
)

router = APIRouter(prefix="/api", tags=["api"])

#: Upload limits of one report from the Mini App. Telegram's own bot limit is 50 MB per file,
#: which is also what the worker can forward to Mila; ten files is an album.
MAX_UPLOAD_FILES = 10
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024


@router.get("/me", response_model=schemas.Me)
async def me(principal: PrincipalDep) -> schemas.Me:
    user = principal.user
    return schemas.Me(id=user.id, first_name=user.first_name, username=user.username, is_admin=principal.is_admin)


@router.post("/session", response_model=schemas.Me)
async def open_session(
    body: schemas.SessionIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> schemas.Me:
    """Validate initData once and set the cookie that lets `<img src=/media/…>` load."""
    info = auth.validate_init_data(body.init_data, settings.bot_token, now=now)
    if info is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid init data")
    user = await people.upsert_user(
        session,
        TelegramUser(id=info.id, username=info.username, first_name=info.first_name, last_name=info.last_name),
        now=now,
    )
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.make_session_token(settings.bot_token, user.id, now=now),
        max_age=int(auth.SESSION_MAX_AGE.total_seconds()),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return schemas.Me(
        id=user.id,
        first_name=user.first_name,
        username=user.username,
        is_admin=user.is_admin or settings.is_admin(user.id),
    )


# --- home: task, today, passport ---------------------------------------------------


@router.get("/home", response_model=schemas.HomeOut)
async def home(
    principal: PrincipalDep, session: SessionDep, season: SeasonDep, today: TodayDep, settings: SettingsDep
) -> schemas.HomeOut:
    await people.ensure_member(session, season.id, principal.user.id, now=principal.user.joined_at)
    return await views.home_out(
        session,
        season=season,
        user_id=principal.user.id,
        today=today,
        principal_admin=principal.is_admin,
        settings=settings,
    )


@router.post("/intent", response_model=schemas.IntentOut)
async def set_intent(
    body: schemas.IntentIn,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    now: NowDep,
) -> schemas.IntentOut:
    """«Берусь · Попробую · В этот раз мимо» — the same row Mila's summary and the reminders read."""
    week = await content.week_by_number(session, season.id, body.week_number)
    if week is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such week")
    await people.set_intent(
        session,
        season_id=season.id,
        user_id=principal.user.id,
        week_id=week.id,
        choice=models.IntentChoice(body.choice),
        now=now,
    )
    await _notify_admin(
        session,
        settings,
        principal,
        f"👤 {ru.escape(principal.user.display_name_with_username)} — "
        f"<b>{ru.INTENT_NAMES[body.choice]}</b> на неделе {week.number}",
        now=now,
    )
    return schemas.IntentOut(choice=body.choice, hint=ru.INTENT_HINTS[body.choice])


# --- reports -----------------------------------------------------------------------


async def _chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(_CHUNK):
        yield chunk


@router.post("/reports", response_model=schemas.ReportResult, status_code=status.HTTP_201_CREATED)
async def submit_report(
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    media_store: MediaStoreDep,
    now: NowDep,
    response: Response,
    text: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form(max_length=64)] = "",
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — FastAPI reads the default as «no files»
) -> schemas.ReportResult:
    """A report from the Mini App: text and/or files, judged by the bot's rules (DOMAIN §2).

    Files are streamed straight onto the media disk and hashed before the row is marked
    downloaded — the same guarantee as for files fetched from Telegram. Mila gets the usual
    copy with the header she can reply to, the participant the usual receipt in the chat.
    `client_id` makes a retry harmless: the same id answers with the report already made.
    """
    body = text.strip()
    uploads = [upload for upload in files if upload.filename or upload.size]
    if not body and not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "пустой отчёт: нужен текст или файл")
    if len(uploads) > MAX_UPLOAD_FILES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"не больше {MAX_UPLOAD_FILES} файлов за раз")
    if client_id:
        existing = await reports.find_by_client_id(session, user_id=principal.user.id, client_id=client_id)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return await _already_submitted(session, season, existing)

    incoming_files = [_incoming_file(upload) for upload in uploads]
    kind = incoming_files[0].kind if incoming_files else ReportKind.TEXT
    incoming = IncomingMessage(kind=kind, text=body or None, files=incoming_files, client_id=client_id or None)
    result = await reports.accept(session, season_id=season.id, user_id=principal.user.id, message=incoming, now=now)
    await _store_uploads(session, media_store, result.media_ids, uploads, now)

    author = principal.user.display_name_with_username
    if result.out_of_week or result.week_number is None:
        message = ru.OUT_OF_WEEK
        header = ru.admin_out_of_week_header(author, incoming.text, kind.value)
        week_id = None
        letter = await letters.create(
            session,
            season_id=season.id,
            user_id=principal.user.id,
            source=letters.Source.OUT_OF_WEEK,
            text=incoming.text,
            report_id=result.report_id,
            now=now,
        )
        letter_id: int | None = letter.id
    else:
        week = await content.week_by_number(session, season.id, result.week_number)
        assert week is not None
        message = ru.report_reply(week, result.stamp_level or result.level, freeze_granted=result.freeze_granted)
        header = ru.admin_report_header(week.number, author, incoming.text, kind.value)
        week_id = week.id
        letter_id = None
    await _notify_admin(
        session,
        settings,
        principal,
        header,
        media_ids=result.media_ids,
        report_id=result.report_id,
        week_id=week_id,
        letter_id=letter_id,
        now=now,
    )
    await notify.enqueue_message(session, chat_id=principal.user.id, text=message, now=now)
    return schemas.ReportResult(
        report_id=result.report_id,
        week_number=result.week_number,
        out_of_week=result.out_of_week,
        level=result.level.value,
        stamp_level=result.stamp_level.value if result.stamp_level else None,
        freeze_granted=result.freeze_granted,
        message=message,
    )


def _incoming_file(upload: UploadFile) -> IncomingFile:
    return IncomingFile(
        kind=media_service.kind_for_mime(upload.content_type),
        file_id=None,
        mime=upload.content_type or "application/octet-stream",
        size=upload.size,
    )


async def _store_uploads(
    session: SessionDep,
    media_store: MediaStoreDep,
    media_ids: Sequence[uuid.UUID],
    uploads: Sequence[UploadFile],
    now: NowDep,
) -> None:
    for media_id, upload in zip(media_ids, uploads, strict=True):
        try:
            await media_store.receive_upload(session, media_id, _chunks(upload), now=now, max_bytes=MAX_UPLOAD_BYTES)
        except media_service.UploadTooLargeError as exc:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ"
            ) from exc


async def _already_submitted(session: SessionDep, season: SeasonDep, row: models.Report) -> schemas.ReportResult:
    """The answer to a retried submission: what the first attempt produced, sent nowhere again."""
    from romantika.services import stamps

    week = await session.get(models.Week, row.week_id) if row.week_id is not None else None
    if week is None:
        return schemas.ReportResult(
            report_id=row.id,
            week_number=None,
            out_of_week=True,
            level=row.level,
            stamp_level=None,
            freeze_granted=False,
            message=ru.OUT_OF_WEEK,
        )
    stamp = await stamps.get_level(session, user_id=row.user_id, week_id=week.id)
    week_dto = await content.week_by_number(session, season.id, week.number)
    assert week_dto is not None
    return schemas.ReportResult(
        report_id=row.id,
        week_number=week.number,
        out_of_week=False,
        level=row.level,
        stamp_level=stamp.value if stamp else None,
        freeze_granted=False,
        message=ru.report_reply(week_dto, stamp or StampLevel(row.level), freeze_granted=False),
    )


@router.patch("/reports/{report_id}", response_model=schemas.ReportEditOut)
async def edit_report(
    report_id: int,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    media_store: MediaStoreDep,
    today: TodayDep,
    now: NowDep,
    text: Annotated[str, Form()] = "",
    remove: Annotated[list[str], Form()] = [],  # noqa: B006 — media ids to hide
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 — files to add
) -> schemas.ReportEditOut:
    """Change the text and the files of one's own report while its week is open (DOMAIN §2).

    Removed files are hidden, not deleted; the week's stamp is recomputed like after «это не
    отчёт». Mila gets a copy of the change (with the new files), the participant a receipt.
    """
    uploads = [upload for upload in files if upload.filename or upload.size]
    try:
        remove_ids = [uuid.UUID(raw) for raw in remove if raw]
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "неверный id файла") from exc
    row = await session.get(models.Report, report_id)
    live = 0
    if row is not None:
        live = len(
            [m for m in await _report_media(session, report_id) if m.hidden_at is None and m.id not in remove_ids]
        )
    if live + len(uploads) > MAX_UPLOAD_FILES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"не больше {MAX_UPLOAD_FILES} файлов в отчёте")

    result = await reports.edit(
        session,
        user_id=principal.user.id,
        report_id=report_id,
        text=text,
        new_files=[_incoming_file(upload) for upload in uploads],
        remove_media_ids=remove_ids,
        now=now,
    )
    if not result.ok:
        if result.reason == reports.NOT_YOURS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, ru.NOT_REPORT_FOREIGN)
        if result.reason == reports.CANCELLED:
            raise HTTPException(status.HTTP_409_CONFLICT, ru.NOT_REPORT_ALREADY)
        if result.reason == reports.EMPTY:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "пустой отчёт: нужен текст или файл")
        raise HTTPException(status.HTTP_409_CONFLICT, ru.EDIT_WEEK_OVER)
    await _store_uploads(session, media_store, result.media_ids, uploads, now)

    assert result.week_number is not None
    week = await content.week_by_number(session, season.id, result.week_number)
    assert week is not None
    message = ru.edit_reply(week, result.stamp_level, freeze_granted=result.freeze_granted)
    await _notify_admin(
        session,
        settings,
        principal,
        ru.admin_edit_header(
            week.number,
            principal.user.display_name_with_username,
            (text or "").strip() or None,
            added=len(result.media_ids),
            removed=result.removed,
        ),
        media_ids=result.media_ids,
        report_id=report_id,
        week_id=week.id,
        now=now,
    )
    await notify.enqueue_message(session, chat_id=principal.user.id, text=message, now=now)
    fresh = await views.report_out(session, report_id, today=today)
    assert fresh is not None
    return schemas.ReportEditOut(
        report=fresh,
        stamp_level=result.stamp_level.value if result.stamp_level else None,
        freeze_granted=result.freeze_granted,
        message=message,
    )


async def _report_media(session: SessionDep, report_id: int) -> list[models.Media]:
    from sqlalchemy import select

    query = select(models.Media).where(models.Media.report_id == report_id)
    return list((await session.execute(query)).scalars())


@router.post("/reports/{report_id}/cancel", response_model=schemas.CancelOut)
async def cancel_report(
    report_id: int,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    now: NowDep,
) -> schemas.CancelOut:
    """«Это не отчёт, а сообщение Миле»: the stamp is recomputed, the text goes to Mila."""
    cancelled = await reports.cancel(session, user_id=principal.user.id, report_id=report_id, now=now)
    if not cancelled.ok:
        if cancelled.reason == "already_cancelled":
            return schemas.CancelOut(ok=False, stamp_level=None, message=ru.NOT_REPORT_ALREADY)
        raise HTTPException(status.HTTP_403_FORBIDDEN, ru.NOT_REPORT_FOREIGN)
    row = await session.get(models.Report, report_id)
    letter = await letters.create(
        session,
        season_id=season.id,
        user_id=principal.user.id,
        source=letters.Source.NOT_REPORT,
        text=row.text if row else None,
        report_id=report_id,
        now=now,
    )
    await _notify_admin(
        session,
        settings,
        principal,
        ru.admin_letter_header(principal.user.display_name_with_username, row.text if row else None, corrected=True),
        report_id=report_id,
        letter_id=letter.id,
        now=now,
    )
    return schemas.CancelOut(
        ok=True,
        stamp_level=cancelled.stamp_level.value if cancelled.stamp_level else None,
        message=ru.NOT_REPORT_DONE,
    )


@router.post("/weeks/{week_number}/level", response_model=schemas.LevelOut)
async def fix_level(
    week_number: int,
    body: schemas.LevelIn,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    now: NowDep,
) -> schemas.LevelOut:
    """«Это был максимум/минимум»: upgrade only, and only with a report (DOMAIN §2)."""
    level = StampLevel(body.level)
    result = await reports.fix_level(
        session, season_id=season.id, user_id=principal.user.id, week_number=week_number, level=level, now=now
    )
    if result.ok:
        message = f"Поправила — засчитано как <b>{ru.level_name(level)}</b>."
    elif result.reason == reports.NO_DOWNGRADE:
        message = "Максимум не понижаю — звёздочка остаётся ⭐"
    else:
        message = "За эту неделю отчёта нет — пришли текст или фото."
    return schemas.LevelOut(
        ok=result.ok, stamp_level=result.stamp_level.value if result.stamp_level else None, message=message
    )


@router.post("/letters", response_model=schemas.MessageOut)
async def send_letter(
    body: schemas.TextIn,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    now: NowDep,
) -> schemas.MessageOut:
    """«Написать Миле»: not a report, no stamp; stored in her inbox, answered from the chat or the app."""
    letter = await letters.create(
        session,
        season_id=season.id,
        user_id=principal.user.id,
        source=letters.Source.APP,
        text=body.text,
        now=now,
    )
    await _notify_admin(
        session,
        settings,
        principal,
        ru.admin_letter_header(principal.user.display_name_with_username, body.text.strip()),
        letter_id=letter.id,
        now=now,
    )
    return schemas.MessageOut(message=ru.LETTER_SENT)


# --- dictionary and facts ----------------------------------------------------------


@router.get("/dictionary", response_model=schemas.DictionaryOut)
async def dictionary(
    principal: PrincipalDep, session: SessionDep, season: SeasonDep, today: TodayDep
) -> schemas.DictionaryOut:
    view = await words.season_dictionary(session, season.id, today=today)
    names = await people.display_names(session, [item.user_id for item in view.user_words], short=True)
    return schemas.DictionaryOut(
        about=season.title,
        week_words=[
            schemas.WeekWordOut(week_number=w.number, title=w.title, word=w.word, word_ru=w.word_ru, meaning=w.meaning)
            for w in view.week_words
        ],
        user_words=[
            schemas.UserWordOut(
                id=w.id,
                word=w.word,
                meaning=w.meaning,
                author=names.get(w.user_id, str(w.user_id)),
                mine=w.user_id == principal.user.id,
            )
            for w in view.user_words
        ],
    )


@router.post("/words", response_model=schemas.WordAdded, status_code=status.HTTP_201_CREATED)
async def add_word(
    body: schemas.TextIn,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    today: TodayDep,
    now: NowDep,
) -> schemas.WordAdded:
    """«Добавить своё слово» — «слово — значение» in one line; the first one earns a freeze."""
    week = await content.current_week(session, season.id, today=today)
    result = await words.add(
        session,
        season_id=season.id,
        user_id=principal.user.id,
        week_id=week.id if week else None,
        raw=body.text.strip(),
        now=now,
    )
    await _notify_admin(
        session,
        settings,
        principal,
        f"📖 {ru.escape(principal.user.display_name_with_username)} добавил слово: {ru.escape(body.text.strip())}",
        now=now,
    )
    return schemas.WordAdded(
        word=result.word,
        meaning=result.meaning,
        freeze_granted=result.freeze_granted,
        message=ru.WORD_SAVED + (ru.WORD_FREEZE_BONUS if result.freeze_granted else ""),
    )


@router.get("/facts", response_model=schemas.FactsOut)
async def list_facts(principal: PrincipalDep, session: SessionDep, season: SeasonDep) -> schemas.FactsOut:
    listed = await facts.list_active(session, season.id)
    names = await people.display_names(session, [f.author_id for f in listed if f.author_id is not None], short=True)
    return schemas.FactsOut(
        about=season.title_accusative or season.title,
        facts=[
            schemas.FactItem(
                id=f.id,
                text=f.text,
                author=names.get(f.author_id) if f.author_id is not None else None,
                mine=f.author_id == principal.user.id,
                created_at=f.created_at,
            )
            for f in listed
        ],
    )


@router.post("/facts", response_model=schemas.MessageOut, status_code=status.HTTP_201_CREATED)
async def add_fact(
    body: schemas.TextIn,
    principal: PrincipalDep,
    session: SessionDep,
    season: SeasonDep,
    settings: SettingsDep,
    today: TodayDep,
    now: NowDep,
) -> schemas.MessageOut:
    """«Добавить свой факт»; Mila's own facts carry no author, like in the bot."""
    week = await content.current_week(session, season.id, today=today)
    await facts.add(
        session,
        season_id=season.id,
        week_id=week.id if week else None,
        text=body.text.strip(),
        author_id=None if principal.is_admin else principal.user.id,
        now=now,
    )
    if principal.is_admin:
        total = len(await facts.list_active(session, season.id))
        return schemas.MessageOut(message=f"Записала. Фактов за сезон: <b>{total}</b>")
    await _notify_admin(
        session,
        settings,
        principal,
        f"💡 {ru.escape(principal.user.display_name_with_username)} добавил факт: {ru.escape(body.text.strip())}",
        now=now,
    )
    return schemas.MessageOut(message=ru.FACT_SAVED)


# --- journal and PDF ---------------------------------------------------------------


@router.get("/journal", response_model=schemas.JournalOut)
async def my_journal(
    principal: PrincipalDep, session: SessionDep, season: SeasonDep, today: TodayDep
) -> schemas.JournalOut:
    await people.ensure_member(session, season.id, principal.user.id, now=principal.user.joined_at)
    return await views.journal_out(
        session, season=season, user_id=principal.user.id, today=today, principal_admin=principal.is_admin
    )


@router.post("/journal/pdf", response_model=schemas.JobOut, status_code=status.HTTP_202_ACCEPTED)
async def request_pdf(principal: PrincipalDep, session: SessionDep, season: SeasonDep, now: NowDep) -> schemas.JobOut:
    job_id = await jobs.enqueue(
        session,
        "journal_pdf",
        {"user_id": principal.user.id, "season_id": season.id, "chat_id": principal.user.id, "requested_via": "web"},
        now=now,
    )
    return schemas.JobOut(job_id=job_id, status="queued")


async def _own_job(job_id: int, principal: PrincipalDep, session: SessionDep) -> jobs.JobDetail:
    job = await jobs.get(session, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job")
    if job.payload.get("user_id") != principal.user.id and not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your journal")
    return job


@router.get("/journal/pdf/{job_id}", response_model=schemas.JobOut)
async def pdf_status(job_id: int, principal: PrincipalDep, session: SessionDep) -> schemas.JobOut:
    job = await _own_job(job_id, principal, session)
    url = f"/api/journal/pdf/{job_id}/file" if job.status == "done" and job.payload.get("result_path") else None
    return schemas.JobOut(
        job_id=job.id, status=job.status, url=url, error=job.error if job.status == "failed" else None
    )


@router.get("/journal/pdf/{job_id}/file")
async def pdf_file(
    job_id: int, principal: PrincipalDep, session: SessionDep, media_store: MediaStoreDep
) -> FileResponse:
    job = await _own_job(job_id, principal, session)
    relative = job.payload.get("result_path")
    if job.status != "done" or not relative:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the PDF is not ready")
    path = media_store.full_path(str(relative))
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the PDF file is gone")
    return FileResponse(path, media_type="application/pdf", filename=path.name, headers={"Cache-Control": "private"})


# --- helpers -----------------------------------------------------------------------


async def _notify_admin(
    session: SessionDep,
    settings: SettingsDep,
    principal: Principal,
    text: str,
    *,
    media_ids: Sequence[uuid.UUID] = (),
    report_id: int | None = None,
    week_id: int | None = None,
    letter_id: int | None = None,
    now: NowDep,
) -> None:
    """Queue a copy for Mila the way the bot sends it; silent for Mila's own actions."""
    admin_chat = settings.admin_chat
    if admin_chat is None or principal.user.id == admin_chat:
        return
    await notify.enqueue_message(
        session,
        chat_id=admin_chat,
        text=text,
        media_ids=media_ids,
        link_user_id=principal.user.id,
        link_report_id=report_id,
        link_week_id=week_id,
        link_letter_id=letter_id,
        now=now,
    )
