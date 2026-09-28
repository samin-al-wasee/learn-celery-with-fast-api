import logging

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.models import ExportJob, ExportStatus, User
from app.schemas.envelope import ApiResponse
from app.schemas.exports import ExportJobResponse
from app.worker.tasks import export_records

router = APIRouter(tags=["exports"])
logger = logging.getLogger("uvicorn.error")


def _response(job: ExportJob) -> ExportJobResponse:
    prefix = get_settings().api_v1_prefix
    return ExportJobResponse(
        id=job.id,
        status=job.status,
        row_count=job.row_count,
        error=job.error,
        created_at=job.created_at,
        download_url=f"{prefix}/exports/{job.id}/download" if job.status == ExportStatus.SUCCEEDED else None,
    )


async def _owned_job(db: AsyncSession, job_id: str, user: User) -> ExportJob:
    # M3: 404 (not 403) for someone else's job, so job ids can't be probed for existence.
    job = (
        await db.execute(select(ExportJob).where(ExportJob.id == job_id, ExportJob.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise CardicheckError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="EXPORT_NOT_FOUND",
            message="export job not found",
        )
    return job


@router.post(
    "/records/export", response_model=ApiResponse[ExportJobResponse], status_code=status.HTTP_202_ACCEPTED
)
async def request_export(
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ExportJobResponse]:
    # M3: job status is app state -> a row in Postgres, not Celery's result backend.
    job = ExportJob(user_id=current_user.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    try:
        await run_in_threadpool(export_records.delay, job.id)
    except Exception:
        logger.exception("export not enqueued job_id=%s", job.id)
        job.status = ExportStatus.FAILED
        job.error = "could not enqueue"
        await db.commit()
        await db.refresh(job)
    response.headers["Location"] = f"{get_settings().api_v1_prefix}/exports/{job.id}"
    return ApiResponse(data=_response(job))


@router.get("/exports/{job_id}", response_model=ApiResponse[ExportJobResponse])
async def get_export(
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ExportJobResponse]:
    return ApiResponse(data=_response(await _owned_job(db, job_id, current_user)))


@router.get("/exports/{job_id}/download", response_class=FileResponse)
async def download_export(
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    job = await _owned_job(db, job_id, current_user)
    if job.status != ExportStatus.SUCCEEDED or job.file_path is None:
        raise CardicheckError(
            status_code=status.HTTP_409_CONFLICT,
            code="EXPORT_NOT_READY",
            message="export is not finished",
        )
    return FileResponse(job.file_path, media_type="text/csv", filename=f"records-{job.id}.csv")
