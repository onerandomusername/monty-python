from typing import List

import sqlalchemy as sa
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Guild(Base):
    """Represents a Discord guild's enabled bot features."""

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    # todo: this should be a many to many relationship
    feature_ids: Mapped[List[str]] = mapped_column(
        MutableList.as_mutable(sa.ARRAY(sa.String(length=50))),
        name="features",
        nullable=False,
        default=[],
        server_default=r"{}",  # noqa: P103
    )

    # features: Mapped[List[Feature]] = relationship(Feature)
