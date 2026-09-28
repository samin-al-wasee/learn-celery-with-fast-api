"""Fake billing provider (think Stripe) the deposit flow calls over HTTP (M6).

Run:  uvicorn services.billing.main:app --port 8200
Fault injection:
  BILLING_SLOW_FIRST_SECONDS  the first request for a charge is recorded, then answered this late
  BILLING_DECLINE=1           every charge is declined
State is in memory: it stands in for an external provider we don't own.
"""
import asyncio
import os
import uuid

from fastapi import FastAPI, Response, status
from pydantic import BaseModel

app = FastAPI(title="billing-service")

_charges: list[dict[str, object]] = []
_by_key: dict[str, dict[str, object]] = {}


class ChargeRequest(BaseModel):
    amount_cents: int
    reference: str
    idempotency_key: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/charges")
async def create_charge(req: ChargeRequest, response: Response) -> dict[str, object]:
    if req.idempotency_key and req.idempotency_key in _by_key:
        return _by_key[req.idempotency_key]
    declined = os.environ.get("BILLING_DECLINE") == "1"
    charge: dict[str, object] = {
        "id": f"ch_{uuid.uuid4().hex[:12]}",
        "reference": req.reference,
        "amount_cents": req.amount_cents,
        "status": "declined" if declined else "succeeded",
    }
    _charges.append(charge)
    if req.idempotency_key:
        _by_key[req.idempotency_key] = charge
    # The charge is already recorded; only the answer is slow (lost/late response).
    await asyncio.sleep(float(os.environ.get("BILLING_SLOW_FIRST_SECONDS", "0")))
    if declined:
        response.status_code = status.HTTP_402_PAYMENT_REQUIRED
    return charge


@app.get("/charges")
async def list_charges(reference: str) -> list[dict[str, object]]:
    return [c for c in _charges if c["reference"] == reference]
