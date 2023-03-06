import re
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship, validates

from .base import Base
from .rollouts import Rollout


NAME_REGEX = re.compile(r"^[A-Z_]+$")


class Feature(MappedAsDataclass, Base):
    """Represents a bot feature."""

    __tablename__ = "features"

    name: Mapped[str] = mapped_column(sa.String(length=50), primary_key=True)
    enabled: Mapped[Optional[bool]] = mapped_column(default=None, server_default=None, nullable=True)
    rollout_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("rollouts.id"), default=None, nullable=True, name="rollout"
    )
    rollout: Mapped[Optional[Rollout]] = relationship(Rollout, default=None)

    @validates("name")
    def validate_name(self, key: str, name: str) -> str:
        """Validate the `name` attribute meets the regex requirement."""
        if not NAME_REGEX.fullmatch(name):
            err = f"The provided feature name '{name}' does not match the name regex {str(NAME_REGEX)}"
            raise ValueError(err)
        return name
