import datetime
from typing import TYPE_CHECKING, Optional

import ormar
import sqlalchemy as sa

from .metadata import BaseMeta


if TYPE_CHECKING:
    import ormar.relations.relation_proxy

    from .feature import Feature


class Rollout(ormar.Model):
    """Represents a feature rollout."""

    class Meta(BaseMeta):
        tablename: str = "rollouts"

    id: int = ormar.Integer(autoincrement=True, primary_key=True)  # type: ignore
    name: str = ormar.String(max_length=100, unique=True)  # type: ignore
    active: bool = ormar.Boolean(default=False, nullable=False)
    rollout_by: Optional[datetime.datetime] = ormar.DateTime(timezone=True, nullable=True)  # type: ignore
    rollout_to_percent: int = ormar.SmallInteger(minimum=0, maximum=100, nullable=False)  # type: ignore
    rollout_hash_low: int = ormar.SmallInteger(minimum=0, maximum=65535, nullable=False)  # type: ignore
    rollout_hash_high: int = ormar.SmallInteger(minimum=0, maximum=65535, nullable=False)  # type: ignore
    update_every: int = ormar.SmallInteger(minimum=15, multiple_of=15, nullable=False, default=15)  # type: ignore
    hashes_last_updated: datetime.datetime = ormar.DateTime(
        timezone=True,
        nullable=False,
        default=datetime.datetime.now,
        server_default=sa.func.now(),
    )  # type: ignore

    if TYPE_CHECKING:
        features: "ormar.relations.relation_proxy.RelationProxy[Feature]" = ormar.ForeignKey(
            Feature,
            virtual=True,
        )  # type: ignore
