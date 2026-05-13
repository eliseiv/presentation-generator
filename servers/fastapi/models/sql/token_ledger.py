from datetime import datetime
from typing import ClassVar, Optional
import uuid

from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime


class TokenLedgerEntry(SQLModel, table=True):
    """
    Append-only audit log for every token movement. Used both for
    accounting ("how much did presentation X cost user Y") and for
    idempotency ("did we already apply Adapty event Z").

    A single ledger row is inserted in the same DB transaction as the
    `users.tokens` mutation that produced it; `balance_after` is the
    snapshot of the user's balance at commit time.
    """

    __tablename__ = "token_ledger_entries"

    # Predictable string reasons so we can grep / index by reason in SQL.
    # ClassVar so SQLModel/Pydantic treat them as constants, not columns.
    REASON_SIGNUP: ClassVar[str] = "signup"
    REASON_ADMIN_CREDIT: ClassVar[str] = "admin_credit"
    REASON_ADAPTY_SUBSCRIPTION_STARTED: ClassVar[str] = "adapty_subscription_started"
    REASON_ADAPTY_SUBSCRIPTION_RENEWED: ClassVar[str] = "adapty_subscription_renewed"
    REASON_ADAPTY_SUBSCRIPTION_CANCELLED: ClassVar[str] = (
        "adapty_subscription_cancelled"
    )
    REASON_ADAPTY_SUBSCRIPTION_EXPIRED: ClassVar[str] = "adapty_subscription_expired"
    REASON_GENERATION_DEBIT: ClassVar[str] = "generation_debit"
    REASON_GENERATION_REFUND: ClassVar[str] = "generation_refund"

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    user_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    delta: int = Field(sa_column=Column(Integer, nullable=False))
    balance_after: int = Field(sa_column=Column(Integer, nullable=False))
    reason: str = Field(sa_column=Column(String, nullable=False, index=True))
    reference_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True, index=True)
    )
    entry_metadata: Optional[dict] = Field(
        default=None,
        sa_column=Column("metadata", JSON, nullable=True),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
