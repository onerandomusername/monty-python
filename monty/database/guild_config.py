from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship

from .base import Base
from .guild import Guild


# n.b. make sure the metadata in config_metadata stays synced to this file and vice versa
class GuildConfig(MappedAsDataclass, Base):
    """Represents a per-guild config."""

    __tablename__ = "guild_config"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("guilds.id"), name="guild", unique=True)
    guild: Mapped[Optional[Guild]] = relationship(Guild, default=None)
    prefix: Mapped[Optional[str]] = mapped_column(sa.String(length=50), nullable=True, default=None)
    github_issues_org: Mapped[Optional[str]] = mapped_column(sa.String(length=39), nullable=True, default=None)
