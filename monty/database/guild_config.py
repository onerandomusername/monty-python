import ormar

from .metadata import BaseMeta


class GuildConfig(ormar.Model):
    """Represents a per-guild config."""

    class Meta(BaseMeta):
        tablename: str = "guild_config"

    id: str = ormar.BigInteger(primary_key=True, autoincrement=False)
    prefix: str = ormar.String(max_length=50, nullable=True, default=None)
