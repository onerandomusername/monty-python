import re
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, validates

from .base import Base


NAME_REGEX = re.compile(r"^[a-z0-9_]+$")

if TYPE_CHECKING:
    hybrid_property = property
else:
    from sqlalchemy.ext.hybrid import hybrid_property


class PackageInfo(Base):
    """Represents the package information for a documentation inventory."""

    __tablename__ = "docs_inventory"

    name: Mapped[str] = mapped_column(
        sa.String(length=50),
        primary_key=True,
    )
    inventory_url: Mapped[str] = mapped_column(sa.Text())
    _base_url: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True, default=None, name="base_url")
    hidden: Mapped[bool] = mapped_column(sa.Boolean(), default=False, server_default="false", nullable=False)
    guilds_whitelist: Mapped[Optional[List[int]]] = mapped_column(
        MutableList.as_mutable(sa.ARRAY(sa.BigInteger)),
        nullable=True,
        default=[],
        server_default=sa.text("ARRAY[]::bigint[]"),
    )
    guilds_blacklist: Mapped[Optional[List[int]]] = mapped_column(
        MutableList.as_mutable(sa.ARRAY(sa.BigInteger)),
        nullable=True,
        default=[],
        server_default=sa.text("ARRAY[]::bigint[]"),
    )

    @hybrid_property
    def base_url(self) -> str:  # noqa: D102
        if self._base_url:
            return self._base_url
        return self.inventory_url.removesuffix("/").rsplit("/", maxsplit=1)[0] + "/"

    @base_url.setter
    def base_url(self, value: Optional[str]) -> None:
        self._base_url = value

    @validates("name")
    def validate_name(self, key: str, name: str) -> str:
        """Validate all names are of the format of valid python package names."""
        if not NAME_REGEX.fullmatch(name):
            err = f"The provided package name '{name}' does not match the name regex {str(NAME_REGEX)}"
            raise ValueError(err)
        return name
