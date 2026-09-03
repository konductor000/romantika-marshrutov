"""Participant files: only the owner and the admin can see them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from romantika.services import media as media_service
from romantika.web.deps import MediaStoreDep, PrincipalDep, SessionDep

router = APIRouter(tags=["media"])


@router.get("/media/{media_id}")
async def get_media(
    media_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, media_store: MediaStoreDep
) -> FileResponse:
    info = await media_service.describe(session, media_id)
    if info is None or info.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file")
    if info.owner_id != principal.user.id and not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your file")
    path = media_store.full_path(info.path)
    if not info.downloaded or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the file is not on the server yet")
    return FileResponse(
        path,
        media_type=info.mime or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )
