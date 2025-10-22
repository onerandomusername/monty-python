import importlib.metadata
import random
from datetime import datetime, timedelta

import disnake
import psutil
from disnake.ext import commands
from disnake.ext.commands import LargeInt

from monty.bot import Monty
from monty.constants import Client, Colours
from monty.utils import helpers
from monty.utils.messages import DeleteButton


# TODO(onerandomusername): heavy refactor of this information
ABOUT = f"""
*A Python and GitHub focused Discord bot to make collaborating on Python projects through Discord easier than ever.*
**Primary features**
### Features
Monty allows for evaluating Python code within Discord, formatting code snippets with Black, and more, in the realm of Python and GitHub.
See a message that you want to keep track of? Use the `Bookmark` command to save it for later!
Auto-expand GitHub links to show rich embeds with issue/PR status, author, labels, and more information.

If you find the default configuration too noisy, Monty also supports per-server configuration to enable/disable features as needed. Use `/config` to get started.
### Get Started
**GitHub**: {Client.git_repo}
**Invite**: [Click here](https://discord.com/oauth2/authorize?client_id={{client_id}}) to add Monty!
**Support**: https://discord.gg/{Client.support_server}
**Credits**: Click the Credits button below to view who helped make Monty possible.
"""  # noqa: E501

CREDITS = """
Monty Python would not have been possible without the following open source projects:
### Primary framework
**disnake**: [Website](https://disnake.dev) | [Server](https://discord.gg/disnake)
### Initial framework and features
python-discord's bot ([source](https://github.com/python-discord/bot))
python-discord's sir-lancebot ([source](https://github.com/python-discord/sir-lancebot))

Note that at this point in time, most of the commonly used features in Monty have been rewritten, though the overall codebase still resembles and mirrors the structure of the original applications.
"""  # noqa: E501

STATUS = """
Git commit: [`{sha_short}`]({git_repo}/commit/{sha})
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

        self._app_info_last_fetched: datetime | None = None

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        # Pre-fetch application info
        appinfo = await self.application_info()
        global ABOUT
        ABOUT = ABOUT.format(client_id=appinfo.id)

    @commands.slash_command(name="monty")
    async def monty(self, inter: disnake.CommandInteraction) -> None:
        """Meta commands."""

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
            disnake.ui.Button(url=Client.git_repo, label="GitHub"),
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
        components: list[DeleteButton] = []
        if not ephemeral:
            components.append(DeleteButton(inter.author))
        await inter.send(embed=e, ephemeral=ephemeral, components=components)

    @monty.sub_command(name="invite")
    async def invite(
        self,
        inter: disnake.CommandInteraction,
        guild_id: LargeInt | None = None,
        raw_link: bool = False,
        ephemeral: bool | None = None,
    ) -> None:
        """
        Generate an invite link to invite Monty.

        Parameters
        ----------
        ephemeral: Whether to send the invite link as an ephemeral message.
        raw_link: Whether to return the raw invite link.
        guild_id: The guild to prefill the invite link with.
        """
        if ephemeral is None:
            ephemeral = bool(inter.guild_id)

        appinfo = await self.application_info()

        urls = helpers.get_invite_link_from_app_info(appinfo)

        message = "Click below to add me!" if not raw_link else "Click the following link to add me!"

        labels = {
            disnake.ApplicationInstallTypes.user.flag: "User install (global commands)",
            disnake.ApplicationInstallTypes.guild.flag: "Guild invite",
        }

        components: list[disnake.ui.Button] = []

        if not ephemeral:
            components.append(DeleteButton(inter.author))

        if raw_link:
            if isinstance(urls, dict):
                message += "\n"
                for num, url in urls.items():
                    title = labels[num]
                    message += title + ": <" + url + ">\n"
            else:
                message += f"\n{urls}"
        elif isinstance(urls, dict):
            for num, url in urls.items():
                title = labels[num]
                components.append(disnake.ui.Button(url=url, style=disnake.ButtonStyle.link, label=title))
        else:
            components.append(
                disnake.ui.Button(
                    url=urls, style=disnake.ButtonStyle.link, label=f"Click to invite {inter.bot.user.name}!"
                )
            )

        await inter.response.send_message(
            message,
            allowed_mentions=disnake.AllowedMentions.none(),
            components=components,
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
            sha_short=(Client.git_sha or "develop")[:7],
            git_repo=Client.git_repo,
            sha=Client.git_sha or "main",
            latency=f"{round(self.bot.latency * 1000)}ms",
            uptime=round(float(self.bot.start_time.format("X"))),
        )

        components = DeleteButton(inter.author)
        await inter.send(embed=e, components=components)

    @monty.sub_command()
    async def support(self, inter: disnake.CommandInteraction, ephemeral: bool | None = None) -> None:
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
            f"https://discord.gg/{Client.support_server}",
            ephemeral=ephemeral,
            components=components,
        )

    async def application_info(self) -> disnake.AppInfo:
        """Fetch the application info using a local hour-long cache."""
        if not self._app_info_last_fetched or helpers.utcnow() - self._app_info_last_fetched > timedelta(hours=0):
            self._cached_app_info = await self.bot.application_info()
            self._app_info_last_fetched = helpers.utcnow()
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
