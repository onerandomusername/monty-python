import importlib.metadata
import random
from datetime import datetime, timedelta
from typing import Optional

import disnake
import psutil
from disnake.ext import commands
from disnake.ext.commands import LargeInt, Range

from monty.bot import Monty
from monty.constants import Client, Colours
from monty.utils.helpers import utcnow
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

**GitHub**: {Client.git_repo}
**Invite**: Use `/monty invite` to get an invite link to add me to your server.
**Support**: https://discord.gg/{Client.support_server}
**Credits**: Click the Credits button below to view who I thank for helping make Monty.
"""

CREDITS = """
Monty Python would not have been possible without the following open source projects:

**Primary library**
**disnake**: [Website](https://disnake.dev) | [Server](https://discord.gg/disnake)

**Initial framework and features**
python-discord's sir-lancebot: ([Repo](https://github.com/python-discord/sir-lancebot))
python-discord's bot: ([Repo](https://github.com/python-discord/bot))

Most initial features (eval, github issues, and similar) were initially forked from python-discord's bot, and modified to work with Monty.
"""  # noqa: E501

STATUS = """
Version: `{version}`
Disnake version: `{disnake_version}`

Guilds: `{guilds}`
Users: `{users}`
Channels: `{channels}`

CPU Usage: `{cpu_usage}%`
Memory Usage: `{memory_usage:.2f} MiB`

Latency: `{latency}`
Up since: <t:{uptime}:R>
"""

PRIVACY = """
Like every piece of software out there, Monty has a privacy policy.
Unlike most pieces of software, this is a very short privacy policy.

The privacy policy in full can be found here: <{privacy_url}>.
"""

COLOURS = (Colours.python_blue, Colours.python_yellow)


class Meta(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Get meta information about the bot."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.process = psutil.Process()

        self._app_info_last_fetched: Optional[datetime] = None

    @commands.slash_command(name="monty")
    async def monty(self, inter: disnake.CommandInteraction) -> None:
        """Meta commands."""
        pass

    @monty.sub_command(name="about")
    async def about(self, inter: disnake.CommandInteraction) -> None:
        """List features, credits, external links."""
        e = disnake.Embed(
            title="About",
            description=ABOUT,
            colour=random.choice(COLOURS),
            timestamp=self.bot.start_time.datetime,
        )

        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.set_footer(text="Last started", icon_url=self.bot.user.display_avatar.url)

        app_info = await self.application_info()
        components = [
            DeleteButton(inter.author),
            disnake.ui.Button(custom_id="meta:v1:credits", style=disnake.ButtonStyle.primary, label="View Credits"),
            disnake.ui.Button(url=app_info.privacy_policy_url, label="Privacy Policy"),
            disnake.ui.Button(url=Client.github_bot_repo, label="GitHub"),
        ]
        await inter.send(embed=e, components=components)

    @commands.Cog.listener("on_message_interaction")
    async def show_credits(self, inter: disnake.MessageInteraction) -> None:
        """Credits of original sources."""
        if inter.component.custom_id != "meta:v1:credits":
            return
        e = disnake.Embed(
            title="Credits",
            description=CREDITS,
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)

        ephemeral = bool(inter.guild_id)
        components = []
        if not ephemeral:
            components.append(DeleteButton(inter.author))
        await inter.send(embed=e, ephemeral=ephemeral, components=components)

    @monty.sub_command(name="invite")
    async def invite(
        self,
        inter: disnake.CommandInteraction,
        permissions: Range[int, 0, disnake.Permissions.all().value] = None,
        guild_id: LargeInt = None,
        raw_link: bool = False,
        ephemeral: bool = None,
    ) -> None:
        """
        Generate an invite link to invite Monty.

        Parameters
        ----------
        permissions: The permissions to grant the invite link.
        guild_id: The guild to invite the bot to.
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
            guild_id=guild_id,
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
        embed.set_footer(text="Up since")
        embed.timestamp = self.bot.start_time.datetime

        components = DeleteButton(inter.author)
        await inter.send(embed=embed, components=components)

    @monty.sub_command(name="status")
    async def status(self, inter: disnake.CommandInteraction) -> None:
        """View the current bot status (uptime, guild count, resource usage, etc)."""
        e = disnake.Embed(
            title="Status",
            colour=random.choice(COLOURS),
        )
        e.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)
        memory_usage = self.process.memory_info()
        memory_usage = memory_usage.rss / 1024**2

        e.description = STATUS.format(
            disnake_version=importlib.metadata.version("disnake"),
            guilds=len(self.bot.guilds),
            users=sum([guild.member_count for guild in self.bot.guilds]),
            channels=sum(len(guild.channels) for guild in self.bot.guilds),
            memory_usage=memory_usage,
            cpu_usage=self.process.cpu_percent(),
            version=Client.version[:7],
            latency=f"{round(self.bot.latency * 1000)}ms",
            uptime=round(float(self.bot.start_time.format("X"))),
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

        if not ephemeral:
            components = (DeleteButton(inter.author, allow_manage_messages=False),)
        else:
            components = []

        await inter.send(
            "If you find yourself in need of support, please join the support server: "
            "https://discord.gg/{invite}".format(invite=Client.support_server),
            ephemeral=ephemeral,
            components=components,
        )

    async def application_info(self) -> disnake.AppInfo:
        """Fetch the application info using a local hour-long cache."""
        if not self._app_info_last_fetched or utcnow() - self._app_info_last_fetched > timedelta(hours=1):
            self._cached_app_info = await self.bot.application_info()
            self._app_info_last_fetched = utcnow()
        return self._cached_app_info

    @monty.sub_command()
    async def privacy(self, inter: disnake.AppCommandInteraction, ephemeral: bool = True) -> None:
        """
        See the privacy policy regarding what information is stored and shared.

        Parameters
        ----------
        ephemeral: Whether to send the privacy information as an ephemeral message.
        """
        appinfo = await self.application_info()
        embed = disnake.Embed(title=f"{self.bot.user.name}'s Privacy Information")
        embed.description = PRIVACY.format(privacy_url=appinfo.privacy_policy_url)
        embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)

        components = DeleteButton(inter.author) if not ephemeral else []
        await inter.response.send_message(embed=embed, ephemeral=ephemeral, components=components)


def setup(bot: Monty) -> None:
    """Load the Meta cog."""
    bot.add_cog(Meta(bot))
