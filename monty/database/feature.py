import functools
import re
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship, validates

from .base import Base
from .rollouts import Rollout


NAME_REGEX = re.compile(r"^[A-Z0-9_]+$")


class Feature(MappedAsDataclass, Base):
    """Represents a bot feature."""

    __tablename__ = "features"

    name: Mapped[str] = mapped_column(sa.String(length=50), primary_key=True)
    enabled: Mapped[Optional[bool]] = mapped_column(default=None, server_default=None, nullable=True)
    rollout_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("rollouts.id"), default=None, nullable=True, name="rollout"
    )
    rollout: Mapped[Optional[Rollout]] = relationship(Rollout, default=None)

    @validates("name")
    def validate_name(self, key: str, name: str) -> str:
        """Validate the `name` attribute meets the regex requirement."""
        if not NAME_REGEX.fullmatch(name):
            err = f"The provided feature name '{name}' does not match the name regex {str(NAME_REGEX)}"
            raise ValueError(err)
        return name


feature_column = functools.partial(mapped_column, sa.Boolean, default=None, nullable=True)


class EntityFeatures(MappedAsDataclass, Base):
    """
    Represents the features that are enabled for a specific entity.

    An entity can be a user or a guild. There is no validation that an entity actually exists.
    Future support may include specific channels, or categories, or even threads.
    It is simply a way to look up a single ID and see what features are enabled for it.
    There is a type column to indicate what type of entity it is, e.g., "user" or "guild".

    To be fair, this may be better done as a seperate table for Guilds and Users,
    though we will often be mixing the two and determining which is overriding which at runtime.

    Each column represents a specific feature that can be toggled on or off for the entity.
    If the value is NULL, then the feature is not explicitly set for the entity, and the global
    feature setting should be used instead.
    If the value is True, then the feature is force-enabled for the entity,
    provided the feature is not force disabled at a higher level (e.g., globally or at the guild level).
    If the value is False, then the feature is disabled for the entity **regardless of any other setting.**
    """

    __tablename__ = "entity_features"

    entity_id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    type_: Mapped[str] = mapped_column(sa.String(length=20), primary_key=True)
    codeblock_recommendations: Mapped[bool] = feature_column()
    discord_token_remover: Mapped[bool] = feature_column()
    discord_webhook_remover: Mapped[bool] = feature_column()
    github_comment_links: Mapped[bool] = feature_column()
    github_discussions: Mapped[bool] = feature_column()
    github_issue_expand: Mapped[bool] = feature_column()
    github_issue_links: Mapped[bool] = feature_column()
    global_source: Mapped[bool] = feature_column()
    inline_docs: Mapped[bool] = feature_column()
    inline_evaluation: Mapped[bool] = feature_column()
    pypi_autocomplete: Mapped[bool] = feature_column()
    python_discourse_autolink: Mapped[bool] = feature_column()
    ruff_rule_v2: Mapped[bool] = feature_column()
    source_autocomplete: Mapped[bool] = feature_column()
