import disnake
from disnake.ext import commands

from bot import start_time
from bot.bot import Bot
from bot.constants import Colours


class Meta(commands.Cog):
    """Get meta information about the bot."""

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
        await inter.send(embed=disnake.Embed(title="Up since:", description=f"<t:{timestamp}:F> (<t:{timestamp}:R>)"))

    @commands.command()
    async def invite(self, ctx: commands.Context, guild: disnake.Object = disnake.utils.MISSING) -> None:
        """Send an invite link to add me."""
        url = disnake.utils.oauth_url(
            self.bot.user.id,
            scopes=["bot", "applications.commands"],
            permissions=disnake.Permissions(412317248704),
            guild=guild,
        )
        await ctx.send(f"<{url}>")


def setup(bot: Bot) -> None:
    """Load the Ping cog."""
    bot.add_cog(Meta(bot))
