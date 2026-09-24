"""claude-ios contract: POST /v1/tokens/purchase and GET /v1/tokens/products."""

from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from api.v1.storekit_common import resolve_storekit_user_id
from services.billing_service import credit_storekit_transaction, list_storekit_products
from services.storekit_jws import parse_and_verify_storekit_jws


TOKENS_ROUTER = APIRouter(tags=["Tokens"])


class TokenPurchaseRequest(BaseModel):
    userId: Optional[str] = Field(
        default=None,
        description="Must match X-User-Id when both are sent.",
    )
    transaction: str = Field(
        min_length=1,
        description="StoreKit 2 Transaction.jwsRepresentation compact JWS.",
    )


class TokenPurchaseResponse(BaseModel):
    creditsAdded: int
    newBalance: int
    transactionId: str


class TokenProduct(BaseModel):
    productId: str
    title: Optional[str] = None
    kind: Optional[str] = None
    period: Optional[str] = None
    price: Optional[int] = None
    currency: Optional[str] = None
    credits: Optional[int] = None
    isSpecialOffer: bool = False
    isDefault: bool = False


class TokenProductsResponse(BaseModel):
    products: list[TokenProduct]


async def _purchase_tokens(
    body: TokenPurchaseRequest,
    x_user_id: Optional[str],
) -> TokenPurchaseResponse:
    user_id = resolve_storekit_user_id(x_user_id, body.userId)
    verified = parse_and_verify_storekit_jws(body.transaction)
    result = await credit_storekit_transaction(
        user_id=user_id,
        transaction=verified,
        expected_kind="tokens",
    )
    return TokenPurchaseResponse(
        creditsAdded=int(result.get("granted_tokens") or 0),
        newBalance=int(result.get("tokens") or 0),
        transactionId=str(result.get("transaction_id") or ""),
    )


@TOKENS_ROUTER.post(
    "/v1/tokens/purchase",
    response_model=TokenPurchaseResponse,
    summary="Купить пакет токенов",
)
@TOKENS_ROUTER.post(
    "/api/v1/tokens/purchase",
    response_model=TokenPurchaseResponse,
    include_in_schema=False,
)
async def purchase_tokens(
    body: TokenPurchaseRequest,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
):
    return await _purchase_tokens(body, x_user_id)


@TOKENS_ROUTER.get(
    "/v1/tokens/products",
    response_model=TokenProductsResponse,
    summary="Каталог пакетов токенов",
)
@TOKENS_ROUTER.get(
    "/api/v1/tokens/products",
    response_model=TokenProductsResponse,
    include_in_schema=False,
)
async def list_token_products():
    return TokenProductsResponse(
        products=[TokenProduct(**item) for item in list_storekit_products()]
    )
