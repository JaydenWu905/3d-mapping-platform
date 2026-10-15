"""Streaming upload API; paths and registry entries are always server-generated."""
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel

from app.services.upload_service import UploadError, UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])
service = UploadService()


class UploadCreate(BaseModel):
    filename: str
    size_bytes: int
    profile_id: str


@router.get("/profiles")
def profiles():
    return service.profiles()


@router.post("", status_code=201)
def create(req: UploadCreate):
    try:
        return service.create(req.filename, req.size_bytes, req.profile_id)
    except UploadError as exc:
        raise HTTPException(422, str(exc))


@router.get("/{upload_id}")
def status(upload_id: str):
    try:
        return service.status(upload_id)
    except UploadError as exc:
        raise HTTPException(404, str(exc))


@router.put("/{upload_id}/chunk")
async def chunk(upload_id: str, request: Request, x_offset: int = Header(), x_chunk_sha256: str = Header()):
    try:
        return await service.chunk(upload_id, x_offset, x_chunk_sha256, request.stream())
    except UploadError as exc:
        raise HTTPException(409, str(exc))


@router.post("/{upload_id}/finalize")
async def finalize(upload_id: str):
    try:
        return await service.finalize(upload_id)
    except UploadError as exc:
        raise HTTPException(422, str(exc))
