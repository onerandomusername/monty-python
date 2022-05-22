from typing import Optional

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.database import GuildConfig
from monty.errors import BotAccountRequired
from monty.utils.messages import DeleteButton


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
        guild_config = await GuildConfig.objects.get_or_none(id=inter.guild_id)
        if not guild_config:
            created = True
            guild_config = GuildConfig(id=inter.guild_id)
        else:
            created = False

        old_prefix = guild_config.prefix
        guild_config.prefix = new_prefix

        if new_prefix and old_prefix:
            msg = f"Successfully changed prefix from `{old_prefix}` to `{new_prefix}`."
        elif new_prefix:
            msg = f"Successfully set prefix to `{new_prefix}`."
        else:
            default_prefix: str = self.bot.command_prefix
            msg = f"Successfully cleared the prefix for this guild. The default prefix is `{default_prefix}`."

        if created:
            await guild_config.save()
        else:
            await guild_config.update()

        await inter.response.send_message(msg, ephemeral=True)

    @prefix.sub_command("clear")
    async def clear_prefix(self, inter: disnake.GuildCommandInteraction) -> None:
        """Clear the existing prefix."""
        await self.set_prefix(inter, None)

    async def _get_prefix_msg(self, guild_id: int) -> str:
        guild_config = await GuildConfig.objects.get_or_none(id=guild_id)
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


def setup(bot: Monty) -> None:
    """Add the configuration cog to the bot."""
    bot.add_cog(Configuration(bot))
