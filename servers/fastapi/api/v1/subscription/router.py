"""claude-ios contract: POST /v1/subscription/sync."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from api.v1.storekit_common import resolve_storekit_user_id
from services.billing_service import credit_storekit_transaction
from services.storekit_jws import parse_and_verify_storekit_jws


SUBSCRIPTION_ROUTER = APIRouter(tags=["Subscription"])


class SubscriptionSyncRequest(BaseModel):
    userId: Optional[str] = Field(
        default=None,
        description="Must match X-User-Id when both are sent.",
    )
    transaction: str = Field(
        min_length=1,
        description="StoreKit 2 Transaction.jwsRepresentation compact JWS.",
    )


class SubscriptionSyncResponse(BaseModel):
    isSubscribed: bool
    expiresAt: Optional[datetime] = None
    plan: Optional[str] = None


async def _sync_subscription(
    body: SubscriptionSyncRequest,
    x_user_id: Optional[str],
) -> SubscriptionSyncResponse:
    user_id = resolve_storekit_user_id(x_user_id, body.userId)
    verified = parse_and_verify_storekit_jws(body.transaction)
    result = await credit_storekit_transaction(
        user_id=user_id,
        transaction=verified,
        expected_kind="subscription",
    )
    expires = result.get("subscription_expires_at")
    expires_at = None
    if expires:
        expires_at = datetime.fromisoformat(expires)
    return SubscriptionSyncResponse(
        isSubscribed=bool(result.get("subscription")),
        expiresAt=expires_at,
        plan=result.get("product_id") or None,
    )


@SUBSCRIPTION_ROUTER.post(
    "/v1/subscription/sync",
    response_model=SubscriptionSyncResponse,
    summary="Синхронизировать подписку",
)
@SUBSCRIPTION_ROUTER.post(
    "/api/v1/subscription/sync",
    response_model=SubscriptionSyncResponse,
    include_in_schema=False,
)
async def subscription_sync(
    body: SubscriptionSyncRequest,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    return await _sync_subscription(body, x_user_id)
