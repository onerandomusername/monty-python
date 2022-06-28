from typing import Optional

import ormar

from .metadata import BaseMeta
from .rollouts import Rollout


name_regex = r"^[A-Z_]+$"


class Feature(ormar.Model):
    """Represents a bot feature."""

    class Meta(BaseMeta):
        tablename: str = "features"

    name: str = ormar.String(primary_key=True, max_length=50, regex=name_regex)  # type: ignore
    enabled: Optional[bool] = ormar.Boolean(default=None, server_default=None, nullable=True)
    rollout: Optional[Rollout] = ormar.ForeignKey(Rollout, nullable=True)  # type: ignore
