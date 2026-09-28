import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import async_session_factory, get_db_session
from app.core.errors import CardicheckError
from app.core.security import decode_access_token
from app.models import Appointment, ChatMessage, User
from app.realtime.hub import hub
from app.schemas.chat import ChatMessageResponse
from app.schemas.envelope import ApiResponse

router = APIRouter(tags=["chat"])

AUTH_TIMEOUT_SECONDS = 5.0
REPLAY_LIMIT = 200


def _frame(msg: ChatMessage) -> dict[str, Any]:
    return {
        "type": "message",
        "id": msg.id,
        "from": msg.sender_id,
        "client_msg_id": msg.client_msg_id,
        "text": msg.text,
        "sent_at": msg.created_at.isoformat(),
    }


async def _authenticate(ws: WebSocket, appointment_id: int) -> tuple[User, int | None] | None:
    # M4: auth is the first frame, not a ?token= query param: uvicorn's access log prints
    # the full WebSocket path, which would write every JWT to the logs.
    try:
        frame = await asyncio.wait_for(ws.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, ValueError):
        return None
    user_id = decode_access_token(str(frame.get("token", ""))) if frame.get("type") == "auth" else None
    if user_id is None:
        return None
    # M4: a short-lived session just for the checks; holding one per open socket would
    # pin a pool connection for the socket's whole lifetime and exhaust the pool.
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        appt = await db.get(Appointment, appointment_id)
    if user is None or appt is None or user.id not in (appt.patient_id, appt.doctor_id):
        return None
    last_seen = frame.get("last_seen_id")
    return user, last_seen if isinstance(last_seen, int) else None


async def _replay(ws: WebSocket, appointment_id: int, after_id: int) -> None:
    async with async_session_factory() as db:
        missed = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.appointment_id == appointment_id, ChatMessage.id > after_id)
                .order_by(ChatMessage.id)
                .limit(REPLAY_LIMIT)
            )
        ).scalars().all()
    for msg in missed:
        await ws.send_json(_frame(msg))


async def _store(appointment_id: int, sender_id: int, client_msg_id: str, text: str) -> tuple[ChatMessage, bool]:
    """Insert once per (sender, client_msg_id); returns (message, created)."""
    async with async_session_factory() as db:
        new_id = (
            await db.execute(
                insert(ChatMessage)
                .values(appointment_id=appointment_id, sender_id=sender_id, client_msg_id=client_msg_id, text=text)
                .on_conflict_do_nothing(constraint="uq_chat_messages_sender_client_msg")
                .returning(ChatMessage.id)
            )
        ).scalar_one_or_none()
        await db.commit()
        msg = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.sender_id == sender_id, ChatMessage.client_msg_id == client_msg_id
                )
            )
        ).scalar_one()
    return msg, new_id is not None


@router.websocket("/ws/appointments/{appointment_id}/chat")
async def chat(ws: WebSocket, appointment_id: int) -> None:
    await ws.accept()
    auth = await _authenticate(ws, appointment_id)
    if auth is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user, last_seen_id = auth
    # M4: subscribe first, then replay from the DB, so nothing falls in between; a message can
    # arrive both live and in the replay, so clients dedup by id.
    await hub.join(appointment_id, ws)
    await ws.send_json({"type": "joined", "appointment_id": appointment_id})
    if last_seen_id is not None:
        await _replay(ws, appointment_id, last_seen_id)
    try:
        while True:
            frame = await ws.receive_json()
            text = str(frame.get("text", "")).strip()[:2000]
            if frame.get("type") != "message" or not text:
                continue
            client_msg_id = str(frame.get("client_msg_id") or uuid.uuid4())[:64]
            # M4: the DB is the log (durable, ordered by id); pub/sub is only the live notification.
            msg, created = await _store(appointment_id, user.id, client_msg_id, text)
            if created:
                await hub.publish(appointment_id, _frame(msg))
            else:
                await ws.send_json({"type": "ack", "client_msg_id": client_msg_id, "id": msg.id})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(appointment_id, ws)


@router.get("/appointments/{appointment_id}/messages", response_model=ApiResponse[list[ChatMessageResponse]])
async def list_messages(
    appointment_id: int,
    before_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[ChatMessageResponse]]:
    appt = await db.get(Appointment, appointment_id)
    if appt is None:
        raise CardicheckError(
            status_code=status.HTTP_404_NOT_FOUND, code="APPOINTMENT_NOT_FOUND", message="appointment not found"
        )
    if current_user.id not in (appt.patient_id, appt.doctor_id):
        raise CardicheckError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="NOT_PARTICIPANT",
            message="only participants may read this chat",
        )
    limit = min(max(limit, 1), 100)
    query = select(ChatMessage).where(ChatMessage.appointment_id == appointment_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    # M4: keyset (cursor) pagination on id, newest first; no OFFSET scans as history grows.
    rows = (await db.execute(query.order_by(ChatMessage.id.desc()).limit(limit))).scalars().all()
    data = [ChatMessageResponse.model_validate(m, from_attributes=True) for m in rows]
    next_before = rows[-1].id if len(rows) == limit else None
    return ApiResponse(data=data, meta={"next_before_id": next_before})
