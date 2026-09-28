"""Availability service: a separate process the booking flow calls over HTTP (M6).

Run:  uvicorn services.availability.main:app --port 8100
Fault injection: AVAILABILITY_DELAY_SECONDS makes every answer slow.
"""
import asyncio
import os
from datetime import datetime

from fastapi import FastAPI

app = FastAPI(title="availability-service")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/availability")
async def availability(doctor_id: int, at: datetime) -> dict[str, object]:
    await asyncio.sleep(float(os.environ.get("AVAILABILITY_DELAY_SECONDS", "0")))
    return {"doctor_id": doctor_id, "at": at.isoformat(), "available": True}
