"""Guild specific commands for disnake & dislash.py."""

import disnake
from disnake.ext import commands

from monty import constants
from monty.bot import Monty


HOW_TO_FORMAT = r"""
Here's how to format Python code on Discord:

\`\`\`py
print('Hello world!')
\`\`\`

These are backticks, not quotes. Check [this](https://superuser.com/questions/254076/how-do-i-type-the-tick-and-backtick-characters-on-windows/254077#254077) out if you can't find the backtick key.
"""  # noqa: E501

DISNAKE_GUILD = constants.Guilds.disnake


class DisnakeCog(commands.Cog, name="Disnake"):
    """Guild specific commands for disnake."""

    def __init__(self, bot: Monty):
        self.bot = bot

    @commands.command("code")
    async def codeblock(self, ctx: commands.Context) -> None:
        """How to format code on discord."""
        await ctx.send(embed=disnake.Embed(description=HOW_TO_FORMAT))

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Ensure these commands are only runnable in the disnake guild."""
        return ctx.guild and ctx.guild.id == DISNAKE_GUILD


def setup(bot: Monty) -> None:
    """Add the guild specific disnake commands to Monty."""
    bot.add_cog(DisnakeCog(bot))
