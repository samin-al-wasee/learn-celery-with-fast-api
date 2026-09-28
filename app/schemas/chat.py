from datetime import datetime

from pydantic import BaseModel


class ChatMessageResponse(BaseModel):
    id: int
    appointment_id: int
    sender_id: int
    client_msg_id: str
    text: str
    created_at: datetime
