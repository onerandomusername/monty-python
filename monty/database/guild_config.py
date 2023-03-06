import re
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship, validates

from .base import Base, dataclass_callable
from .guild import Guild


GITHUB_ORG_REGEX = re.compile(r"[a-zA-Z0-9\-]{1,}")


class GuildConfig(MappedAsDataclass, Base, dataclass_callable=dataclass_callable):
    """Represents a per-guild config."""

    __tablename__ = "guild_config"

    id: Mapped[str] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    guild: Mapped[Optional[Guild]] = relationship(Guild)
    guild_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("guilds.id"), name="guild", unique=True)
    prefix: Mapped[str] = mapped_column(sa.String(length=50), nullable=True, default=None)
    github_issues_org: Mapped[str] = mapped_column(
        sa.String(length=39),
        nullable=True,
        default=None,
    )

    @validates("github_issues_org")
    def validate_github_org(self, key: str, name: str) -> str:
        """Validate all GitHub orgs meet GitHub's naming requirements."""
        if not GITHUB_ORG_REGEX.fullmatch(name):
            err = f"The GitHub org '{name}' is not a valid GitHub organisation name."
            raise ValueError(err)
        return name
