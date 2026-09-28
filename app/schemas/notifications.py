from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    kind: str
    body: str
    appointment_id: int | None
    created_at: datetime
