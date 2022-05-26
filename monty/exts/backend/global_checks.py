import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.errors import BotAccountRequired
from monty.log import get_logger


logger = get_logger(__name__)


class GlobalCheck(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Global checks for monty."""

    def __init__(self, bot: Monty):
        self.bot = bot
        self._bot_invite_link: str = ""

        self._checks = {attr: getattr(self, attr) for attr in dir(self) if attr.startswith("global_check_")}
        self.add_checks()

    @commands.Cog.listener("on_ready")
    async def set_invite_link(self) -> None:
        """Set the invite link when the bot is ready."""
        if self._bot_invite_link:
            return

        class FakeGuild:
            id = "{guild_id}"

        guild = FakeGuild
        self._bot_invite_link = disnake.utils.oauth_url(
            self.bot.user.id,
            disable_guild_select=True,
            guild=guild,
            scopes={"applications.commands", "bot"},
            permissions=self.bot.invite_permissions,
        )

    def add_checks(self) -> None:
        """Adds all checks to the bot."""
        for name, check in self._checks.items():
            if name.startswith("global_check_app_cmd"):
                self.bot.add_app_command_check(
                    check, call_once=True, slash_commands=True, user_commands=True, message_commands=True
                )
            elif name.startswith("global_check_prefix_cmd"):
                self.bot.add_check(check, call_once=True)
            else:
                logger.warn(f"Invalid named check in {type(self).__name__} cog")

    def remove_checks(self) -> None:
        """Removes all cog checks from the bot."""
        for name, check in self._checks.items():
            if name.startswith("global_check_app_cmd"):
                self.bot.remove_app_command_check(
                    check, call_once=True, slash_commands=True, user_commands=True, message_commands=True
                )
            elif name.startswith("global_check_prefix_cmd"):
                self.bot.remove_check(check, call_once=True)
            else:
                # no warning here as it was warned for during load
                pass

    def global_check_app_cmd(self, inter: disnake.CommandInteraction) -> bool:
        """Require all commands be in a guild and have the bot scope."""
        if inter.guild or not inter.guild_id:
            return True

        invite = self._bot_invite_link.format(guild_id=inter.guild_id)
        if inter.permissions.manage_guild:
            msg = (
                f"The bot scope is required to perform any actions. "
                f"You can invite the full bot by [clicking here](<{invite}>)."
            )
        else:
            msg = (
                f"The bot scope is required to perform any actions. "
                f"Please ask a server manager to [invite the full bot](<{invite}>)."
            )
        raise BotAccountRequired(msg)

    def global_check_prefix_cmd(self, ctx: commands.Context) -> bool:
        """Require all commands be in guild."""
        if ctx.guild:
            return True
        raise commands.NoPrivateMessage()

    cog_unload = remove_checks


def setup(bot: Monty) -> None:
    """Add the global checks to the bot."""
    bot.add_cog(GlobalCheck(bot))
