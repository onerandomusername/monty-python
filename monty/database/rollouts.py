import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


if TYPE_CHECKING:
    pass


class Rollout(Base):
    """Represents a feature rollout."""

    __tablename__ = "rollouts"

    id: Mapped[int] = mapped_column(sa.Integer, autoincrement=True, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(length=100), unique=True)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    rollout_by: Mapped[Optional[datetime.datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    rollout_to_percent: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    rollout_hash_low: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    rollout_hash_high: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    update_every: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=15)
    hashes_last_updated: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=datetime.datetime.now,
        server_default=sa.func.now(),
    )
