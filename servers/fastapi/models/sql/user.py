from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Boolean, Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime


class UserModel(SQLModel, table=True):
    """
    One row per iOS caller. The PK is whatever the iOS app sends in the
    `X-User-Id` header (Apple identifierForVendor, custom UUID, etc.).

    `tokens` is the spendable balance. `subscription` is the latest
    Adapty-observed state; it does NOT grant unlimited generation — every
    generation still debits the token balance.
    """

    __tablename__ = "users"

    id: str = Field(primary_key=True)
    tokens: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    subscription: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, default=False)
    )
    subscription_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    adapty_profile_id: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
            onupdate=get_current_utc_datetime,
        ),
    )
