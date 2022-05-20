from typing import List, Optional

import ormar
import ormar_postgres_extensions as ormar_pg_ext
import sqlalchemy

from .metadata import BaseMeta


class PackageInfo(ormar.Model):
    """Represents the package information for a documentation inventory."""

    class Meta(BaseMeta):
        tablename: str = "docs_inventory"

    name: str = ormar.String(primary_key=True, max_length=50, regex=r"^[a-z0-9_]+$")
    inventory_url: str = ormar.Text()
    base_url: Optional[str] = ormar.Text(nullable=True)
    hidden: bool = ormar.Boolean(default=False, server_default="false", nullable=False)
    guilds_whitelist: Optional[List[int]] = ormar_pg_ext.ARRAY(
        item_type=sqlalchemy.BigInteger(),
        nullable=True,
        default=[],
    )
    guilds_blacklist: Optional[List[int]] = ormar_pg_ext.ARRAY(
        item_type=sqlalchemy.BigInteger(),
        nullable=True,
        default=[],
    )
