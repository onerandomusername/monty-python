from typing import Optional

import aiohttp
import disnake
import pydantic
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.database import GuildConfig
from monty.errors import BotAccountRequired
from monty.utils.messages import DeleteButton


GITHUB_REQUEST_HEADERS = {}
if GITHUB_TOKEN := constants.Tokens.github:
    GITHUB_REQUEST_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


class Configuration(
    commands.Cog,
    name="Config Manager",
    slash_command_attrs={"dm_permission": False, "default_member_permissions": disnake.Permissions(manage_guild=True)},
):
    """Configuration management for each guild."""

    def __init__(self, bot: Monty):
        self.bot = bot

    @commands.Cog.listener("on_guild_remove")
    async def remove_config_on_guild_remove(self, guild: disnake.Guild) -> None:
        """Delete the config as soon as we leave a guild."""
        guild_config = await GuildConfig.objects.get_or_none(id=guild.id)

        if not guild_config:
            # nothing to delete
            return

        await guild_config.delete()

        # also remove it from the cache
        try:
            del self.bot.guild_configs[guild.id]
        except KeyError:
            pass

    async def getch_guild_config(self, guild_id: int, *, create: bool = False) -> GuildConfig:
        """Fetch the configuration for the specified guild."""
        guild_config = self.bot.guild_configs.get(guild_id) or await GuildConfig.objects.get_or_none(id=guild_id)
        if not guild_config:
            guild_config = GuildConfig(id=guild_id)
            if create:
                await guild_config.save()
            self.bot.guild_configs[guild_id] = guild_config
        return guild_config

    @commands.slash_command()
    async def config(self, inter: disnake.GuildCommandInteraction) -> None:
        """[ALPHA] Manage per-guild configuration for Monty."""
        pass

    @config.sub_command_group()
    async def prefix(self, inter: disnake.GuildCommandInteraction) -> None:
        """Clear, set, or view the current prefix."""
        if inter.guild:
            return

        invite = disnake.utils.oauth_url(
            self.bot.user.id,
            disable_guild_select=True,
            guild=disnake.Object(inter.guild_id),
            scopes={"applications.commands", "bot"},
            permissions=self.bot.invite_permissions,
        )
        msg = (
            "This command cannot be used without the bot, as the bot must be here to listen for prefixed commands.\n"
            f"You can invite the full bot by [clicking here](<{invite}>)."
        )
        raise BotAccountRequired(msg)

    @prefix.sub_command("set")
    async def set_prefix(self, inter: disnake.GuildCommandInteraction, new_prefix: Optional[str]) -> None:
        """
        Set the prefix for this guild.

        Parameters
        ----------
        new_prefix: the new prefix for commands
        """
        guild_config = await self.getch_guild_config(inter.guild_id)

        old_prefix = guild_config.prefix
        guild_config.prefix = new_prefix

        if new_prefix and old_prefix:
            msg = f"Successfully changed prefix from `{old_prefix}` to `{new_prefix}`."
        elif new_prefix:
            msg = f"Successfully set prefix to `{new_prefix}`."
        else:
            default_prefix: str = self.bot.command_prefix
            msg = f"Successfully cleared the prefix for this guild. The default prefix is `{default_prefix}`."

        await guild_config.upsert()

        await inter.response.send_message(msg, ephemeral=True)

    @prefix.sub_command("clear")
    async def clear_prefix(self, inter: disnake.GuildCommandInteraction) -> None:
        """Clear the existing prefix."""
        await self.set_prefix(inter, None)

    async def _get_prefix_msg(self, guild_id: int) -> str:
        guild_config = self.bot.guild_configs.get(guild_id) or await GuildConfig.objects.get_or_none(id=guild_id)
        prefix = None
        if guild_config:
            prefix = guild_config.prefix

        if prefix:
            return f"The currently configured prefix for this guild is `{prefix}`."
        else:
            default_prefix: str = self.bot.command_prefix
            return f"There is no prefix configured for this guild. The default prefix is `{default_prefix}`"

    @prefix.sub_command("view")
    async def view_prefix(self, inter: disnake.GuildCommandInteraction) -> None:
        """View the currently set prefix, or if none is set, the default prefix."""
        msg = await self._get_prefix_msg(inter.guild_id)
        await inter.response.send_message(msg, ephemeral=True)

    @commands.guild_only()
    @commands.command("prefix", hidden=True)
    async def command_prefix(self, ctx: commands.Context) -> None:
        """Show the currently set prefix for the guild. To set a prefix, use `/config prefix set`."""
        msg = await self._get_prefix_msg(ctx.guild.id)

        await ctx.send(msg, components=DeleteButton(ctx.author, initial_message=ctx.message))

    @config.sub_command_group("github-org")
    async def config_github_org(self, inter: disnake.GuildCommandInteraction) -> None:
        """Configure the default organisation or user for automatic github issue linking."""
        pass

    @config_github_org.sub_command("view")
    async def config_github_org_view(self, inter: disnake.GuildCommandInteraction) -> None:
        """View the currently configured organisation or user for issue linking."""
        guild_config = await self.getch_guild_config(inter.guild_id)
        org = guild_config.github_issues_org
        if org:
            await inter.response.send_message(
                f"The currently configured organisation for issue linking is `{org}`.", ephemeral=True
            )
        else:
            await inter.response.send_message("There is no configured organisation for issue linking.", ephemeral=True)

    @config_github_org.sub_command("set")
    async def config_github_org_set(self, inter: disnake.GuildCommandInteraction, org: str) -> None:
        """
        Set an organisation or user for issue linking.

        Parameters
        ----------
        org: The organisation or user to default to linking issues from.
        """
        guild_config = await self.getch_guild_config(inter.guild_id, create=True)
        try:
            guild_config.github_issues_org = org
            async with self.bot.http_session.head(
                f"https://github.com/{org}", headers=GITHUB_REQUEST_HEADERS, raise_for_status=True
            ):
                pass
        except pydantic.ValidationError:
            raise commands.UserInputError(
                "organsation must be between 1 and 39 characters and only contain alphanumeric characters or hypens."
            )
        except aiohttp.ClientResponseError:
            raise commands.UserInputError("organisation must be a valid github user or organsation.")

        await guild_config.update()

        await inter.response.send_message(
            f"Successfully set the organisation for issue linking to `{org}`.", ephemeral=True
        )

    @config_github_org.sub_command("clear")
    async def config_github_org_clear(self, inter: disnake.GuildCommandInteraction) -> None:
        """Clear the organisation or user from issue linking."""
        guild_config = await self.getch_guild_config(inter.guild_id, create=True)

        guild_config.github_issues_org = None
        await guild_config.upsert()

        await inter.response.send_message("Successfully cleared the organisation for issue linking.", ephemeral=True)


def setup(bot: Monty) -> None:
    """Add the configuration cog to the bot."""
    bot.add_cog(Configuration(bot))
