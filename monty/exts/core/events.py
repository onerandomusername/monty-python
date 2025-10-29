import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.events import MessageContext, MontyEvent
from monty.log import get_logger
from monty.metadata import ExtMetadata


EXT_METADATA = ExtMetadata(core=True)


logger = get_logger(__name__)


class Events(commands.Cog):
    """Global checks for monty."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @commands.Cog.listener(disnake.Event.message)
    async def on_message(self, message: disnake.Message) -> None:
        """Re-dispatch message listener events for on_message commands.

        There are multiple listeners that listen for urls and code content
        so we pre-process that information here before dispatching.
        """
        # Only care about messages from users.
        if message.author.bot:
            return

        context = MessageContext.from_message(message)
        self.bot.dispatch(MontyEvent.monty_message_processed.value, message, context)


def setup(bot: Monty) -> None:
    """Add the events cog the bot."""
    bot.add_cog(Events(bot))
