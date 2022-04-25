import logging
import random
import typing as t
from asyncio import Lock
from functools import wraps
from weakref import WeakValueDictionary

import disnake
from disnake.ext import commands

from monty.constants import ERROR_REPLIES


ONE_DAY = 24 * 60 * 60

log = logging.getLogger(__name__)


class InChannelCheckFailure(commands.CheckFailure):
    """Check failure when the user runs a command in a non-whitelisted channel."""

    pass


class InMonthCheckFailure(commands.CheckFailure):
    """Check failure for when a command is invoked outside of its allowed month."""

    pass


def with_role(*role_ids: int) -> t.Callable:
    """Check to see whether the invoking user has any of the roles specified in role_ids."""

    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild:  # Return False in a DM
            log.debug(
                f"{ctx.author} tried to use the '{ctx.command.name}'command from a DM. "
                "This command is restricted by the with_role decorator. Rejecting request."
            )
            return False

        for role in ctx.author.roles:
            if role.id in role_ids:
                log.debug(f"{ctx.author} has the '{role.name}' role, and passes the check.")
                return True

        log.debug(
            f"{ctx.author} does not have the required role to use "
            f"the '{ctx.command.name}' command, so the request is rejected."
        )
        return False

    return commands.check(predicate)


def without_role(*role_ids: int) -> t.Callable:
    """Check whether the invoking user does not have all of the roles specified in role_ids."""

    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild:  # Return False in a DM
            log.debug(
                f"{ctx.author} tried to use the '{ctx.command.name}' command from a DM. "
                "This command is restricted by the without_role decorator. Rejecting request."
            )
            return False

        author_roles = [role.id for role in ctx.author.roles]
        check = all(role not in author_roles for role in role_ids)
        log.debug(
            f"{ctx.author} tried to call the '{ctx.command.name}' command. "
            f"The result of the without_role check was {check}."
        )
        return check

    return commands.check(predicate)


def locked() -> t.Union[t.Callable, None]:
    """
    Allows the user to only run one instance of the decorated command at a time.

    Subsequent calls to the command from the same author are ignored until the command has completed invocation.

    This decorator has to go before (below) the `command` decorator.
    """

    def wrap(func: t.Callable) -> t.Union[t.Callable, None]:
        func.__locks = WeakValueDictionary()

        @wraps(func)
        async def inner(self: t.Callable, ctx: commands.Context, *args, **kwargs) -> t.Union[t.Callable, None]:
            lock = func.__locks.setdefault(ctx.author.id, Lock())
            if lock.locked():
                embed = disnake.Embed()
                embed.colour = disnake.Colour.red()

                log.debug("User tried to invoke a locked command.")
                embed.description = (
                    "You're already using this command. Please wait until " "it is done before you use it again."
                )
                embed.title = random.choice(ERROR_REPLIES)
                await ctx.send(embed=embed)
                return

            async with func.__locks.setdefault(ctx.author.id, Lock()):
                return await func(self, ctx, *args, **kwargs)

        return inner

    return wrap
