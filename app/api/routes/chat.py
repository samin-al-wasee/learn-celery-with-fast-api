import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.database import async_session_factory
from app.core.security import decode_access_token
from app.models import Appointment, User
from app.realtime.hub import hub

router = APIRouter(tags=["chat"])

AUTH_TIMEOUT_SECONDS = 5.0


async def _authenticate(ws: WebSocket, appointment_id: int) -> User | None:
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
    return user


@router.websocket("/ws/appointments/{appointment_id}/chat")
async def chat(ws: WebSocket, appointment_id: int) -> None:
    await ws.accept()
    user = await _authenticate(ws, appointment_id)
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await hub.join(appointment_id, ws)
    await ws.send_json({"type": "joined", "appointment_id": appointment_id})
    try:
        while True:
            frame = await ws.receive_json()
            text = str(frame.get("text", "")).strip()
            if frame.get("type") != "message" or not text:
                continue
            await hub.publish(
                appointment_id,
                {
                    "type": "message",
                    "from": user.id,
                    "text": text[:2000],
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(appointment_id, ws)
