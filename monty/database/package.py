import re
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, validates

from .base import Base


NAME_REGEX = re.compile(r"^[a-z0-9_]+$")


class PackageInfo(Base):
    """Represents the package information for a documentation inventory."""

    __tablename__ = "docs_inventory"

    name: Mapped[str] = mapped_column(
        sa.String(length=50),
        primary_key=True,
    )
    inventory_url: Mapped[str] = mapped_column(sa.Text())
    base_url: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True, default=None)
    hidden: Mapped[bool] = mapped_column(sa.Boolean(), default=False, server_default="false", nullable=False)
    guilds_whitelist: Mapped[Optional[List[int]]] = mapped_column(
        sa.ARRAY(sa.BigInteger),
        nullable=True,
        default=[],
        server_default=sa.text("ARRAY[]::bigint[]"),
    )
    guilds_blacklist: Mapped[Optional[List[int]]] = mapped_column(
        sa.ARRAY(sa.BigInteger),
        nullable=True,
        default=[],
        server_default=sa.text("ARRAY[]::bigint[]"),
    )

    @validates("name")
    def validate_name(self, key: str, name: str) -> str:
        """Validate all names are of the format of valid python package names."""
        if not NAME_REGEX.fullmatch(name):
            err = f"The provided package name '{name}' does not match the name regex {str(NAME_REGEX)}"
            raise ValueError(err)
        return name
