import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.log import get_logger


logger = get_logger(__name__)


class GlobalCheck(commands.Cog):
    """Global checks for monty."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self._bot_invite_link: str = ""

    async def cog_load(self) -> None:
        """Run set_invite_link after the bot is ready."""
        await self.bot.wait_until_ready()
        await self.set_invite_link()

    async def set_invite_link(self) -> None:
        """Set the invite link for the bot."""
        if self._bot_invite_link:
            return

        # todo: don't require a fake guild object
        class FakeGuild:
            id: str = "{guild_id}"

        guild = FakeGuild
        self._bot_invite_link = disnake.utils.oauth_url(
            self.bot.user.id,
            disable_guild_select=True,
            guild=guild,  # type: ignore # this is totally wrong
            scopes={"applications.commands", "bot"},
            permissions=self.bot.invite_permissions,
        )

    async def bot_check_once(self, ctx: commands.Context) -> bool:
        """Require all commands be in guild."""
        if ctx.guild:
            return True
        raise commands.NoPrivateMessage()


def setup(bot: Monty) -> None:
    """Add the global checks to the bot."""
    bot.add_cog(GlobalCheck(bot))
