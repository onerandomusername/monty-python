import collections
from typing import TYPE_CHECKING

import disnake
from disnake.ext import commands

from monty.bot import get_logger
from monty.metadata import ExtMetadata
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    from monty.bot import Monty

EXT_METADATA = ExtMetadata(core=True)

log = get_logger(__name__)


class GatewayLog(commands.Cog):
    """Logs gateway events."""

    def __init__(self, bot: "Monty") -> None:
        self.bot = bot
        self.log = get_logger("monty.gateway")

    @property
    def socket_events(self) -> collections.Counter[str]:
        """A counter of all logged events."""
        return self.bot.socket_events

    @commands.Cog.listener()
    async def on_socket_event_type(self, event_type: str) -> None:
        """Logs all socket events."""
        self.log.debug(f"Socket event: {event_type}")
        self.socket_events[event_type] += 1

    @commands.command(name="gw", hidden=True)
    async def gateway(self, ctx: commands.Context) -> None:
        """Displays gateway event statistics."""
        name_padding = max(map(len, self.socket_events))
        count_padding = max(len(f"{count:,}") for count in self.socket_events.values()) if self.socket_events else 0
        output = (
            "\n".join(
                f"**`{event: <{name_padding}}`**`{count: >{count_padding},}`"
                for event, count in sorted(self.socket_events.items(), key=lambda x: x[1], reverse=True)
            )
            or "No events have been logged yet."
        )
        components = [
            disnake.ui.TextDisplay(output),
            DeleteButton(
                ctx.author.id,
                allow_manage_messages=False,
                initial_message=(
                    ctx.message if ctx.guild and ctx.channel.permissions_for(ctx.guild.me).manage_messages else None
                ),
            ),
        ]
        await ctx.send(components=components, allowed_mentions=disnake.AllowedMentions.none())

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Enforce only the bot owner can use these commands."""
        if not await self.bot.is_owner(ctx.author):
            msg = "This command can only be used by the bot owner(s)."
            raise commands.NotOwner(msg)
        return True


def setup(bot: "Monty") -> None:
    """Loads the GatewayLog cog."""
    bot.add_cog(GatewayLog(bot))
