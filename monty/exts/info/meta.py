import random

import disnake
import psutil
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import Client, Colours
from monty.utils.delete import DeleteView
from monty.utils.messages import wait_for_deletion


ABOUT = f"""
Based off of multiple open source projects, Monty is a development tool for Discord servers.

**Primary features**
`/docs` Python documentation command
`-eval` Evaluate Python code
`-black` Blacken Python code

**Additional features**
- Leaked token alerting
- Automatic github issue linking
- Inline docs and eval
- Automatic leaked webhook deletion
- Codeblock detection

**GitHub**: {Client.github_bot_repo}
**Credits**: Run `/monty credits` for a list of original sources.
**Invite**: Use `/invite` to get an invite link to add me to your server.
"""

CREDITS = """
Monty python would not have been possible without the following open source projects:

**Primary library**
**disnake**: ([Website](https://disnake.dev))

**Initial framework and features**
python-discord's **sir-lancebot**: ([Repo](https://github.com/pythondiscord/sir-lancebot))
python-discord's **bot**: ([Repo](https://github.com/pythondiscord/bot))

A majority of features were initially implemented on python-discord's **bot**, and modified to work with Monty.
"""

STATS = """
Version: `stable`
Disnake version: `{disnake_version} {disnake_version_level}`

Guilds: `{guilds}`
Users: `{users}`
Channels: `{channels}`

CPU Usage: `{cpu_usage}%`
Memory Usage: `{memory_usage}%`
"""

COLOURS = (Colours.python_blue, Colours.python_yellow)


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
        timestamp = round(float(self.bot.start_time.format("X")))
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

    @commands.slash_command(name="monty")
    async def monty(self, inter: disnake.CommandInteraction) -> None:
        """Meta commands."""
        pass

    @monty.sub_command(name="about")
    async def about(self, inter: disnake.CommandInteraction) -> None:
        """About monty."""
        e = disnake.Embed(
            title="About",
            description=ABOUT,
            colour=random.choice(COLOURS),
            timestamp=self.bot.start_time.datetime,
        )

        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.set_footer(text="Last started", icon_url=self.bot.user.display_avatar.url)

        view = DeleteView(inter.author, inter)
        await inter.send(embed=e, view=view)
        self.bot.loop.create_task(wait_for_deletion(inter, view=view))

    @monty.sub_command(name="credits")
    async def credits(self, inter: disnake.CommandInteraction) -> None:
        """Credits of original sources."""
        e = disnake.Embed(
            title="Credits",
            description=CREDITS,
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)

        await inter.send(embed=e, ephemeral=True)

    @monty.sub_command(name="stats")
    async def status(self, inter: disnake.CommandInteraction) -> None:
        """Stats about the current session."""
        e = disnake.Embed(
            title="Stats",
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)

        e.description = STATS.format(
            disnake_version=disnake.__version__,
            disnake_version_level=disnake.version_info.releaselevel,
            guilds=len(self.bot.guilds),
            users=len(self.bot.users),
            channels=sum(len(guild.channels) for guild in self.bot.guilds),
            memory_usage=psutil.virtual_memory().percent,
            cpu_usage=psutil.cpu_percent(),
        )

        view = DeleteView(inter.author, inter)
        await inter.send(embed=e, view=view)
        self.bot.loop.create_task(wait_for_deletion(inter, view=view))


def setup(bot: Bot) -> None:
    """Load the Ping cog."""
    bot.add_cog(Meta(bot))
