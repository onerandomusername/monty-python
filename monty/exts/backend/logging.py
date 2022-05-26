import sys
import traceback
from typing import Any

import disnake
from disnake.ext import commands

from monty.bot import Bot
from monty.log import get_logger
from monty.metadata import ExtMetadata


EXT_METADATA = ExtMetadata(core=True)
logger = get_logger(__name__)


class InternalLogger(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Internal logging for debug and abuse handling."""

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context, command: Any = None, spl: str = None) -> None:
        """Log a command invoke."""
        if not spl:
            spl = ctx.message.content
        spl = spl.split("\n")
        if command is None:
            command: commands.Command = ctx.command
        qualname = command.qualified_name.replace(".", "_")
        self.bot.stats.incr("prefix_commands." + qualname + ".uses")
        logger.info(
            "command {command!s} {author!s} ({author.id}) in {channel!s} ({channel.id}): {content}".format(
                author=ctx.author,
                channel=ctx.channel,
                command=command,
                content=spl[0] + (" ..." if len(spl) > 1 else ""),
            )
        )

    @commands.Cog.listener()
    async def on_error(self, event_method: Any, *args, **kwargs) -> None:
        """Log all errors without other listeners."""
        print(f"Ignoring exception in {event_method}", file=sys.stderr)
        traceback.print_exc()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Log a successful command completion."""
        logger.info(f"command by {ctx.author} has completed!")

        qualname = ctx.command.qualified_name.replace(".", "_")
        self.bot.stats.incr("prefix_commands." + qualname + ".completion")

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log the start of a slash command."""
        spl = str(inter.filled_options).replace("\n", " ")
        spl = spl.split("\n")
        # todo: fix this in disnake
        if inter.application_command is disnake.utils.MISSING:
            return
        qualname = inter.application_command.qualified_name.replace(".", "_")
        self.bot.stats.incr("slash_commands." + qualname + ".uses")

        logger.info(
            "Slash command `{command!s}` by {author!s} ({author.id}) in {channel!s} ({channel.id}): {content}".format(
                author=inter.author,
                channel=inter.channel,
                command=inter.application_command.qualified_name,
                content=spl[0] + (" ..." if len(spl) > 1 else ""),
            )
        )

    @commands.Cog.listener()
    async def on_slash_command_completion(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log slash command completion."""
        qualname = inter.application_command.qualified_name.replace(".", "_")
        self.bot.stats.incr("slash_commands." + qualname + ".completion")
        logger.info(f"slash command by {inter.author} has completed!")


def setup(bot: Bot) -> None:
    """Add the internal logger cog to the bot."""
    bot.add_cog(InternalLogger(bot))
