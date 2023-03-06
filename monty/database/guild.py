from typing import List

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .feature import Feature


class Guild(Base):
    """Represents a Discord guild's enabled bot features."""

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=False)
    feature_ids: Mapped[List[str]] = mapped_column(
        sa.ARRAY(sa.String(length=50)),
        name="features",
        nullable=False,
        default=[],
        server_default=r"{}",  # noqa: P103
    )

    features: Mapped[List[Feature]] = relationship(sa.ForeignKey(Feature.name))
