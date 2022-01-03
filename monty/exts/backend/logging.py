import logging
import sys
import traceback
from typing import Any

import disnake
from disnake.ext import commands

from monty.bot import Bot


logger = logging.getLogger(__name__)


class InternalLogger(commands.Cog):
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
            command = ctx.command
        logger.info(
            "command {command!s} {author!s} ({author.id}) in {channel!s} ({channel.id}): {content}".format(
                author=ctx.author,
                channel=ctx.channel,
                command=command,
                content=spl[0] + (" ..." if len(spl) > 1 else ""),
            )
        )

    async def on_error(self, event_method: Any, *args, **kwargs) -> None:
        """Log all errors without other listeners."""
        print(f"Ignoring exception in {event_method}", file=sys.stderr)
        traceback.print_exc()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Log a successful command completion."""
        logger.info(f"command by {ctx.author} has completed!")

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log the start of a slash command."""
        spl = str({opt.name: opt.value for opt in inter.data.options}).replace("\n", " ")
        spl = spl.split("\n")
        logger.info(
            "Slash command `{command!s}` by {author!s} ({author.id}) in {channel!s} ({channel.id}): {content}".format(
                author=inter.author,
                channel=inter.channel,
                command=inter.application_command.name,
                content=spl[0] + (" ..." if len(spl) > 1 else ""),
            )
        )

    @commands.Cog.listener()
    async def on_slash_command_completion(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log slash command completion."""
        logger.info(f"slash command by {inter.author} has completed!")

    @commands.Cog.listener()
    async def on_slash_command_error(
        self,
        inter: disnake.ApplicationCommandInteraction,
        error: commands.CommandError,
    ) -> None:
        """Log slash command errors."""
        logger.exception(
            "{author!s} ({author.id}) in {channel!s} ({channel.id}): {content}".format(
                author=inter.author,
                channel=inter.channel,
                content=str({opt.name: opt.value for opt in inter.data.options}).replace("\n", " "),
            ),
            exc_info=error,
        )


def setup(bot: Bot) -> None:
    """Add the internal logger cog to the bot."""
    bot.add_cog(InternalLogger(bot))
