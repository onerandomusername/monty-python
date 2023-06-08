from datetime import timedelta

import disnake
import disnake.http
from disnake.ext import commands

from monty.log import get_logger
from monty.utils.helpers import utcnow


log = get_logger(__name__)


class Command(commands.Command):
    """
    A `discord.ext.commands.Command` subclass which supports root aliases.

    A `root_aliases` keyword argument is added, which is a sequence of alias names that will act as
    top-level commands rather than being aliases of the command's group. It's stored as an attribute
    also named `root_aliases`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.root_aliases = kwargs.get("root_aliases", [])

        if not isinstance(self.root_aliases, (list, tuple)):
            raise TypeError("Root aliases of a command must be a list or a tuple of strings.")


class Group(commands.Group):
    """
    A `discord.ext.commands.Group` subclass which supports root aliases.

    A `root_aliases` keyword argument is added, which is a sequence of alias names that will act as
    top-level groups rather than being aliases of the command's group. It's stored as an attribute
    also named `root_aliases`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.root_aliases = kwargs.get("root_aliases", [])

        if not isinstance(self.root_aliases, (list, tuple)):
            raise TypeError("Root aliases of a group must be a list or a tuple of strings.")


def patch_typing() -> None:
    """
    Sometimes discord turns off typing events by throwing 403's.

    Handle those issues by patching the trigger_typing method so it ignores 403's in general.
    """
    log.debug("Patching send_typing, which should fix things breaking when discord disables typing events. Stay safe!")

    original = disnake.http.HTTPClient.send_typing
    last_403 = None

    async def honeybadger_type(self, channel_id: int) -> None:  # noqa: ANN001
        nonlocal last_403
        if last_403 and (utcnow() - last_403) < timedelta(minutes=5):
            log.warning("Not sending typing event, we got a 403 less than 5 minutes ago.")
            return
        try:
            await original(self, channel_id)
        except disnake.Forbidden:
            last_403 = utcnow()
            log.warning("Got a 403 from typing event!")
            pass

    disnake.http.HTTPClient.send_typing = honeybadger_type  # type: ignore


original_inter_send = disnake.Interaction.send


def patch_inter_send() -> None:
    """Patch disnake.Interaction.send to always send a message, even if we encounter a race condition."""
    log.debug("Patching disnake.Interaction.send before a fix is submitted to the upstream version.")

    async def always_send(self: disnake.Interaction, *args, **kwargs) -> None:
        try:
            return await original_inter_send(self, *args, **kwargs)
        except disnake.HTTPException as e:
            if e.code != 40060:  # interaction already responded
                raise
            return await self.followup.send(*args, **kwargs)  # type: ignore

    disnake.Interaction.send = always_send
