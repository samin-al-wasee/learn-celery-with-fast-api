import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.routes.chat import _authenticate
from app.core.database import async_session_factory
from app.models import Appointment
from app.realtime.hub import call_hub

router = APIRouter(tags=["call"])

SIGNALS = {"offer", "answer", "candidate", "hangup"}


@router.websocket("/ws/appointments/{appointment_id}/call")
async def call_signaling(ws: WebSocket, appointment_id: int) -> None:
    await ws.accept()
    auth = await _authenticate(ws, appointment_id)
    if auth is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user, _ = auth
    async with async_session_factory() as db:
        appt = await db.get(Appointment, appointment_id)
    assert appt is not None
    peer_id = appt.doctor_id if user.id == appt.patient_id else appt.patient_id
    # M7: every socket is one device of one user; signaling is addressed, not broadcast.
    device_id = uuid.uuid4().hex
    await call_hub.join(appointment_id, ws, user_id=user.id, device_id=device_id)
    await ws.send_json({"type": "joined", "appointment_id": appointment_id, "device_id": device_id, "peer_id": peer_id})
    try:
        while True:
            frame = await ws.receive_json()
            if frame.get("type") not in SIGNALS:
                continue
            # M7: the server stamps the sender and only lets you address the other participant,
            # so a frame never echoes back to its sender and can't be aimed at outsiders.
            frame.update({"from": user.id, "from_device": device_id, "to": peer_id})
            if frame["type"] == "answer":
                # M7: a user on several devices gets the offer on each; only the first answer
                # may win. SET NX is atomic across API processes, so exactly one device claims it.
                key = f"call:{appointment_id}:{frame.get('call_id')}:answered_by"
                if not await call_hub.redis.set(key, device_id, nx=True, ex=120):
                    await ws.send_json({"type": "error", "code": "ALREADY_ANSWERED", "call_id": frame.get("call_id")})
                    continue
                await call_hub.publish(
                    appointment_id,
                    {"type": "answered_elsewhere", "call_id": frame.get("call_id"), "to": user.id,
                     "exclude_device": device_id},
                )
            await call_hub.publish(appointment_id, frame)
    except WebSocketDisconnect:
        pass
    finally:
        await call_hub.leave(appointment_id, ws)
