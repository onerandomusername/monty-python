"""
Utils for managing features.

This provides a util for a feature in the database to be created representing a specific local feature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional, TypeVar, Union

import disnake
from disnake.ext import commands

from monty.constants import Feature
from monty.database.feature import NAME_REGEX
from monty.errors import FeatureDisabled


if TYPE_CHECKING:
    from monty.bot import Monty


AnyContext = Union[disnake.ApplicationCommandInteraction, commands.Context]
T = TypeVar("T")


def require_feature(name: Feature) -> Callable[[T], T]:
    """Require the specified feature for this command."""
    # validate the name meets the regex
    assert name in Feature
    match = NAME_REGEX.fullmatch(name.value)
    if not match:
        raise RuntimeError(f"Feature value must match regex '{NAME_REGEX.pattern}'")

    async def predicate(ctx: AnyContext) -> bool:
        bot: Monty = ctx.bot  # type: ignore # this will be a Monty instance

        guild_id: Optional[int] = getattr(ctx, "guild_id", None) or (ctx.guild and ctx.guild.id)

        is_enabled = await bot.guild_has_feature(guild_id, name)
        if is_enabled:
            return True

        raise FeatureDisabled()

    return commands.check(predicate)
