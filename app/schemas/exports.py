from datetime import datetime

from pydantic import BaseModel

from app.models.export_job import ExportStatus


class ExportJobResponse(BaseModel):
    id: str
    status: ExportStatus
    row_count: int | None
    error: str | None
    created_at: datetime
    download_url: str | None
