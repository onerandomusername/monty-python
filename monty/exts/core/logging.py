import traceback
from typing import Any, Optional

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.log import get_logger
from monty.metadata import ExtMetadata


EXT_METADATA = ExtMetadata(core=True)
logger = get_logger(__name__)


class InternalLogger(commands.Cog):
    """Internal logging for debug and abuse handling."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_command(
        self, ctx: commands.Context, command: Optional[commands.Command] = None, content: str = None
    ) -> None:
        """Log a command invoke."""
        if not isinstance(content, str):
            content = ctx.message.content
        spl = content.split("\n")
        if not command:
            command = ctx.command
        qualname = command.qualified_name if command else "unknown"
        self.bot.stats.incr("prefix_commands." + qualname.replace(".", "_") + ".uses")
        logger.info(
            "command %s by %s (%s) in channel %s (%s) in guild %s: %s",
            qualname,
            ctx.author,
            ctx.author.id,
            ctx.channel,
            ctx.channel.id,
            ctx.guild and ctx.guild.id,
            spl[0] + (" ..." if len(spl) > 1 else ""),
        )

    @commands.Cog.listener()
    async def on_error(self, event_method: Any, *args, **kwargs) -> None:
        """Log all errors without other listeners."""
        logger.error(f"Ignoring exception in {event_method}:\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        """Log a successful command completion."""
        qualname = ctx.command.qualified_name if ctx.command else "unknown"
        logger.info(
            "command %s by %s (%s) in channel %s (%s) in guild %s has completed!",
            qualname,
            ctx.author,
            ctx.author.id,
            ctx.channel,
            ctx.channel.id,
            ctx.guild and ctx.guild.id,
        )

        self.bot.stats.incr("prefix_commands." + qualname.replace(".", "_") + ".completion")

    @commands.Cog.listener()
    async def on_slash_command(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log the start of a slash command."""
        spl = str(inter.filled_options).replace("\n", " ")
        spl = spl.split("\n")
        # todo: fix this in disnake
        if inter.application_command is disnake.utils.MISSING:
            return
        qualname = inter.application_command.qualified_name
        self.bot.stats.incr("slash_commands." + qualname.replace(".", "_") + ".uses")

        logger.info(
            "slash command `%s` by %s (%s) in channel %s (%s) in guild %s: %s",
            inter.application_command.qualified_name,
            inter.author,
            inter.author.id,
            inter.channel,
            inter.channel_id,
            inter.guild_id,
            spl[0] + (" ..." if len(spl) > 1 else ""),
        )

    @commands.Cog.listener()
    async def on_slash_command_completion(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Log slash command completion."""
        qualname = inter.application_command.qualified_name
        self.bot.stats.incr("slash_commands." + qualname.replace(".", "_") + ".completion")
        logger.info(
            "slash command `%s` by %s (%s) in channel %s (%s) in guild %s has completed!",
            qualname,
            inter.author,
            inter.author.id,
            inter.channel,
            inter.channel_id,
            inter.guild_id,
        )


def setup(bot: Monty) -> None:
    """Add the internal logger cog to the bot."""
    bot.add_cog(InternalLogger(bot))
