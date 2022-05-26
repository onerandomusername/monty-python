import ormar

from .metadata import BaseMeta


class GuildConfig(ormar.Model):
    """Represents a per-guild config."""

    class Meta(BaseMeta):
        tablename: str = "guild_config"

    id: str = ormar.BigInteger(primary_key=True, autoincrement=False)  # type: ignore
    prefix: str = ormar.String(max_length=50, nullable=True, default=None)  # type: ignore
    github_issues_org: str = ormar.String(
        max_length=39, min_length=1, nullable=True, default=None, regex=r"[a-zA-Z0-9\-]+"
    )  # type: ignore
