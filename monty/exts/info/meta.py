import random

import disnake
import psutil
from disnake.ext import commands
from disnake.ext.commands import Range

from monty.bot import Monty
from monty.constants import Client, Colours
from monty.utils.messages import DeleteButton


ABOUT = f"""
Based off of multiple open source projects, Monty is a development tool for Discord servers.

**Primary features**
`/docs` View Python documentation from discord
`/pep` View PEPs directly within discord
`-eval` Evaluate Python code
`-black` Blacken Python code

**Additional features**
- Leaked token alerting
- Automatic github issue linking
- Inline docs and eval
- Automatic leaked webhook deletion
- Codeblock detection

**GitHub**: {Client.github_bot_repo}
**Support**: https://discord.gg/{Client.support_server}
**Credits**: Run `/monty credits` for a list of original sources.
**Invite**: Use `/monty invite` to get an invite link to add me to your server.
"""

CREDITS = """
Monty Python would not have been possible without the following open source projects:

**Primary library**
**disnake**: [Website](https://disnake.dev) | [Server](https://discord.gg/disnake)

**Initial framework and features**
python-discord's **sir-lancebot**: ([Repo](https://github.com/python-discord/sir-lancebot))
python-discord's **bot**: ([Repo](https://github.com/python-discord/bot))

A majority of features were initially implemented on python-discord's **bot**, and modified to work with Monty.
"""

STATS = """
Version: `{version}`
Disnake version: `{disnake_version} {disnake_version_level}`

Guilds: `{guilds}`
Users: `{users}`
Channels: `{channels}`

CPU Usage: `{cpu_usage}%`
Memory Usage: `{memory_usage:.2f} MiB`
"""

COLOURS = (Colours.python_blue, Colours.python_yellow)


class Meta(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Get meta information about the bot."""

    def __init__(self, bot: Monty):
        self.bot = bot
        self.process = psutil.Process()

    @commands.slash_command(name="monty", dm_permission=True)
    async def monty(self, inter: disnake.CommandInteraction) -> None:
        """Meta commands."""
        pass

    @monty.sub_command(name="about")
    async def about(self, inter: disnake.CommandInteraction) -> None:
        """About Monty."""
        e = disnake.Embed(
            title="About",
            description=ABOUT,
            colour=random.choice(COLOURS),
            timestamp=self.bot.start_time.datetime,
        )

        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.set_footer(text="Last started", icon_url=self.bot.user.display_avatar.url)

        components = DeleteButton(inter.author)
        await inter.send(embed=e, components=components)

    @monty.sub_command(name="credits")
    async def credits(self, inter: disnake.CommandInteraction) -> None:
        """Credits of original sources."""
        e = disnake.Embed(
            title="Credits",
            description=CREDITS,
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)

        await inter.send(embed=e, ephemeral=bool(inter.guild_id))

    @monty.sub_command(name="invite")
    async def invite(
        self,
        inter: disnake.CommandInteraction,
        permissions: Range[0, disnake.Permissions.all().value] = None,
        guild: str = None,
        raw_link: bool = False,
        ephemeral: bool = None,
    ) -> None:
        """
        Generate an invite link to invite Monty.

        Parameters
        ----------
        permissions: The permissions to grant the invite link.
        guild: The guild to invite the bot to.
        raw_link: Whether to return the raw invite link.
        ephemeral: Whether to send the invite link as an ephemeral message.
        """
        if ephemeral is None:
            ephemeral = bool(inter.guild_id)

        # ignore because we don't have any spaces in the command name
        # therefore, it will always be a slash command and not a subcommand or group
        discord_command: commands.InvokableSlashCommand = self.bot.get_slash_command("discord")  # type: ignore

        if not discord_command:
            raise commands.CommandError("Could not create an invite link right now.")
        invite_command = discord_command.children["app-invite"]
        await invite_command(
            inter,
            client_id=self.bot.user.id,
            permissions=permissions,
            guild=guild,
            include_applications_commands=True,
            raw_link=raw_link,
            ephemeral=ephemeral,
        )

    @monty.sub_command()
    async def ping(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Ping the bot to see its latency and state."""
        embed = disnake.Embed(
            title=":ping_pong: Pong!",
            colour=Colours.bright_green,
            description=f"Gateway Latency: {round(self.bot.latency * 1000)}ms",
        )
        components = DeleteButton(inter.author)
        await inter.send(embed=embed, components=components)

    @monty.sub_command(name="stats")
    async def status(self, inter: disnake.CommandInteraction) -> None:
        """Stats about the current session."""
        e = disnake.Embed(
            title="Stats",
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)
        memory_usage = self.process.memory_info()
        memory_usage = memory_usage.rss / 1024**2
        e.description = STATS.format(
            disnake_version=disnake.__version__,
            disnake_version_level=disnake.version_info.releaselevel,
            guilds=len(self.bot.guilds),
            users=sum([guild.member_count for guild in self.bot.guilds]),
            channels=sum(len(guild.channels) for guild in self.bot.guilds),
            memory_usage=memory_usage,
            cpu_usage=self.process.cpu_percent(),
            version=Client.version[:7],
        )

        components = DeleteButton(inter.author)
        await inter.send(embed=e, components=components)

    @monty.sub_command()
    async def support(self, inter: disnake.CommandInteraction, ephemeral: bool = None) -> None:
        """
        Get a link to the support server.

        Parameters
        ----------
        ephemeral: Whether to send the invite link as an ephemeral message.
        """
        if ephemeral is None:
            ephemeral = bool(inter.guild_id)
        await inter.send(
            "If you find yourself in need of support, please join the support server: "
            "https://discord.gg/{invite}".format(invite=Client.support_server),
            ephemeral=ephemeral,
        )

    @monty.sub_command()
    async def uptime(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Get the current uptime of the bot."""
        timestamp = round(float(self.bot.start_time.format("X")))
        embed = disnake.Embed(title="Up since:", description=f"<t:{timestamp}:F> (<t:{timestamp}:R>)")

        components = DeleteButton(inter.author)
        await inter.send(embed=embed, components=components)


def setup(bot: Monty) -> None:
    """Load the Ping cog."""
    bot.add_cog(Meta(bot))
