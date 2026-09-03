"""Participant API: who am I, my journal, my PDF."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from romantika.services import jobs
from romantika.web import auth, schemas, views
from romantika.web.deps import MediaStoreDep, NowDep, PrincipalDep, SeasonDep, SessionDep, SettingsDep, TodayDep

router = APIRouter(prefix="/api", tags=["api"])


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
    from romantika.services import people
    from romantika.services.people import TelegramUser

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


@router.get("/journal", response_model=schemas.JournalOut)
async def my_journal(
    principal: PrincipalDep, session: SessionDep, season: SeasonDep, today: TodayDep
) -> schemas.JournalOut:
    from romantika.services import people

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
