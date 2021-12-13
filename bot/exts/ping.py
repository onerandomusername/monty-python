import disnake
from disnake.ext import commands

from bot import start_time
from bot.bot import Bot
from bot.constants import Colours


class Ping(commands.Cog):
    """Get info about the bot's ping and uptime."""

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.slash_command()
    async def ping(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Ping the bot to see its latency and state."""
        embed = disnake.Embed(
            title=":ping_pong: Pong!",
            colour=Colours.bright_green,
            description=f"Gateway Latency: {round(self.bot.latency * 1000)}ms",
        )

        await inter.send(embed=embed)

    # Originally made in 70d2170a0a6594561d59c7d080c4280f1ebcd70b by lemon & gdude2002
    @commands.slash_command(name="uptime")
    async def uptime(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Get the current uptime of the bot."""
        timestamp = round(float(start_time.format("X")))
        await inter.send(f"Start time: <t:{timestamp}:R>")


def setup(bot: Bot) -> None:
    """Load the Ping cog."""
    bot.add_cog(Ping(bot))
