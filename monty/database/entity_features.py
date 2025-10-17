"""Entity to feature mapping for an entity and what features are enabled for it."""

import enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .feature import FeatureStatusEnum


class EntityType(enum.Enum):
    """Types that a feature entity can be."""

    GUILD = "guild"
    USER = "user"


class EntityFeatures(Base):
    """Represents a Discord entity's enabled bot features."""

    __tablename__ = "entity_features"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    type: Mapped[EntityType] = mapped_column(sa.Enum(EntityType), primary_key=True)

    # include each individual feature below
    # each feature follows the form of mapped_column(sa.Enum(FeatureStatusEnum), default=None, nullable=True)
    github_features: Mapped[FeatureStatusEnum] = mapped_column(sa.Enum(FeatureStatusEnum), default=None, nullable=True)
