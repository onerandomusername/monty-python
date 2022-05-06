from disnake.ext import commands

from monty.bot import Monty


class DevTools(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Command for inviting a bot."""

    def __init__(self, bot: Monty):
        self.bot = bot


def setup(bot: Monty) -> None:
    """Add the devtools cog to the bot."""
    bot.add_cog(DevTools(bot))
