import enum
import re

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column

from .base import Base


NAME_REGEX = re.compile(r"^[A-Z0-9_]+$")


# while this can be a bool/None, using an enum allows for future expansion if needed
# this may be expanded to add additional types in the future
class FeatureStatusEnum(enum.Enum):
    """Status of a feature for an entity."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    DEFAULT = "default"


class FeatureStatus(MappedAsDataclass, Base):
    """Represents a bot feature."""

    __tablename__ = "features"

    name: Mapped[str] = mapped_column(sa.String(length=50), primary_key=True)
    status: Mapped[bool] = mapped_column(sa.Boolean, default=True)
