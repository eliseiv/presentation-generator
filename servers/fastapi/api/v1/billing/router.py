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

import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
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
from services.llm_cost_service import get_cost_summary, get_presentation_cost
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


def _verify_adapty_token(authorization: Optional[str]) -> None:
    """
    Adapty does not sign payloads — it just lets the operator attach a
    static custom header to every webhook delivery. We use the standard
    `Authorization: Bearer <token>` shape and compare the token against
    `ADAPTY_WEBHOOK_SECRET` with constant-time comparison.
    """
    secret = (get_adapty_webhook_secret_env() or "").strip()
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="ADAPTY_WEBHOOK_SECRET is not configured on the server.",
        )
    if not authorization:
        raise HTTPException(
            status_code=401, detail="Missing Authorization header."
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.strip().lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be 'Bearer <token>'.",
        )
    if not hmac.compare_digest(token.strip(), secret):
        raise HTTPException(status_code=401, detail="Invalid Adapty token.")


@BILLING_ROUTER.post(
    "/adapty/webhook",
    summary="Adapty webhook receiver",
)
async def adapty_webhook(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _verify_adapty_token(authorization)

    # Empty body / non-JSON body / non-object body are all treated as
    # "Adapty is just verifying the URL is alive" and answered with 200.
    # Real events always arrive as a JSON object; the apply_adapty_event
    # function still validates required fields inside.
    raw_body = await request.body()
    if not raw_body:
        logger.info("Adapty webhook ignored: empty body (URL verification ping).")
        return {"status": "ignored", "reason": "empty_body"}

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.info("Adapty webhook ignored: body is not valid JSON.")
        return {"status": "ignored", "reason": "invalid_json"}

    if not isinstance(payload, dict):
        logger.info("Adapty webhook ignored: body is not a JSON object.")
        return {"status": "ignored", "reason": "not_an_object"}

    return await apply_adapty_event(payload)


# ----- Cost / usage reporting (admin) ----------------------------------------
# IMPORTANT: declare `/cost/summary` BEFORE `/cost/{presentation_id}` —
# FastAPI matches routes in registration order, so a literal "summary"
# path otherwise gets captured by the {presentation_id} variable.


@BILLING_ROUTER.get(
    "/cost/summary",
    summary="Агрегированный отчёт по затратам",
)
async def admin_get_cost_summary(
    user_id: Optional[str] = Query(default=None, description="Фильтр по user_id."),
    since: Optional[str] = Query(
        default=None,
        description="ISO 8601 datetime, e.g. 2026-05-01T00:00:00Z",
    ),
    until: Optional[str] = Query(
        default=None,
        description="ISO 8601 datetime, e.g. 2026-05-31T23:59:59Z",
    ),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """
    Возвращает суммарные затраты, среднюю стоимость генерации и разбивку
    по типу вызова за период. Только админ.
    """
    _verify_admin_key(x_admin_key)

    def parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid datetime '{value}': {exc}",
            ) from exc

    return await get_cost_summary(
        user_id=user_id,
        since=parse_dt(since),
        until=parse_dt(until),
    )


@BILLING_ROUTER.get(
    "/cost/{presentation_id}",
    summary="Сколько стоила конкретная презентация",
)
async def admin_get_presentation_cost(
    presentation_id: str,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """
    Возвращает разбивку реальных upstream-затрат (OpenAI / Google / Whisper /
    Vision) по одной презентации. Только админ.
    """
    _verify_admin_key(x_admin_key)
    return await get_presentation_cost(presentation_id)
