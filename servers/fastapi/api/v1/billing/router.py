"""
Billing endpoints — wallet inspection, admin top-up, Adapty webhook.

All paths sit under `/api/v1/billing` so they pass the global
ServiceApiKeyMiddleware that gates `/api/*`. On top of that:

- `GET /me` requires the iOS `X-User-Id` header.
- `POST /credit` requires `X-Admin-Key` == ADMIN_API_KEY env (an
  operator key separate from the iOS SERVICE_API_KEY so it can be
  rotated independently).
- `POST /adapty/webhook` requires a valid HMAC-SHA256 signature in the
  `Adapty-Signature` header, computed against the raw request body.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.billing_service import (
    admin_credit,
    apply_adapty_event,
    get_or_create_user,
    get_subscription_tokens_grant,
    get_token_cost_per_generation,
)
from services.database import get_async_session
from utils.get_env import (
    get_adapty_webhook_secret_env,
    get_admin_api_key_env,
)

logger = logging.getLogger(__name__)

BILLING_ROUTER = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


class WalletResponse(BaseModel):
    user_id: str
    tokens: int
    subscription: bool
    subscription_expires_at: Optional[str] = None
    token_cost_per_generation: int = Field(
        description="Tokens debited per /presentation/generate call."
    )
    subscription_tokens_grant: int = Field(
        description=(
            "Tokens granted on each successful Adapty subscription "
            "started / renewed event."
        )
    )


class AdminCreditRequest(BaseModel):
    user_id: str = Field(..., description="X-User-Id of the recipient.")
    amount: int = Field(..., gt=0, description="Tokens to add to the balance.")
    note: Optional[str] = Field(
        default=None,
        description="Free-form note stored in the ledger entry's metadata.",
    )


class AdminCreditResponse(BaseModel):
    user_id: str
    balance: int


@BILLING_ROUTER.get("/me", response_model=WalletResponse, summary="Get wallet for the current user")
async def get_my_wallet(
    x_user_id: str = Header(..., alias="X-User-Id"),
    sql_session: AsyncSession = Depends(get_async_session),
):
    user = await get_or_create_user(sql_session, x_user_id)
    return WalletResponse(
        user_id=user.id,
        tokens=user.tokens,
        subscription=user.subscription,
        subscription_expires_at=(
            user.subscription_expires_at.isoformat()
            if user.subscription_expires_at
            else None
        ),
        token_cost_per_generation=get_token_cost_per_generation(),
        subscription_tokens_grant=get_subscription_tokens_grant(),
    )


def _verify_admin_key(provided: Optional[str]) -> None:
    configured = (get_admin_api_key_env() or "").strip()
    if not configured:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY is not configured on the server.",
        )
    if not provided or not hmac.compare_digest(provided.strip(), configured):
        raise HTTPException(status_code=401, detail="Invalid admin key.")


@BILLING_ROUTER.post(
    "/credit",
    response_model=AdminCreditResponse,
    summary="Admin top-up: add tokens to a user balance",
)
async def admin_credit_endpoint(
    body: AdminCreditRequest,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    _verify_admin_key(x_admin_key)
    balance = await admin_credit(
        user_id=body.user_id, amount=body.amount, note=body.note
    )
    return AdminCreditResponse(user_id=body.user_id, balance=balance)


def _verify_adapty_signature(raw_body: bytes, provided_signature: Optional[str]) -> None:
    secret = (get_adapty_webhook_secret_env() or "").strip()
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="ADAPTY_WEBHOOK_SECRET is not configured on the server.",
        )
    if not provided_signature:
        raise HTTPException(status_code=401, detail="Missing Adapty signature.")
    provided = provided_signature.strip().lower()
    if provided.startswith("sha256="):
        provided = provided[len("sha256="):]
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid Adapty signature.")


@BILLING_ROUTER.post(
    "/adapty/webhook",
    summary="Adapty webhook receiver",
)
async def adapty_webhook(
    request: Request,
    adapty_signature: Optional[str] = Header(default=None, alias="Adapty-Signature"),
):
    raw_body = await request.body()
    _verify_adapty_signature(raw_body, adapty_signature)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Body is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object.")

    return await apply_adapty_event(payload)
