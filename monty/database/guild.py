from typing import List

import ormar
import ormar_postgres_extensions as ormar_pg_ext

from .feature import Feature
from .metadata import BaseMeta


class Guild(ormar.Model):
    """Represents a Discord guild's enabled bot features."""

    class Meta(BaseMeta):
        tablename: str = "guilds"

    id: int = ormar.BigInteger(primary_key=True, autoincrement=False)  # type: ignore
    features: List[str] = ormar_pg_ext.ARRAY(
        item_type=ormar.ForeignKey(Feature).column_type,
        nullable=False,
        default=[],
        server_default=r"{}",  # noqa: P103
    )  # type: ignore
