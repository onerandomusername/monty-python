from __future__ import annotations

import inspect
from typing import Literal, Union

import disnake
import sqlalchemy as sa
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.config_metadata import METADATA, ConfigAttrMetadata
from monty.database import GuildConfig
from monty.errors import BotAccountRequired
from monty.log import get_logger
from monty.utils.messages import DeleteButton


GITHUB_REQUEST_HEADERS = {}
if GITHUB_TOKEN := constants.Tokens.github:
    GITHUB_REQUEST_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

logger = get_logger(__name__)


@commands.register_injection
async def config_option(inter: disnake.ApplicationCommandInteraction, option: str) -> tuple[str, ConfigAttrMetadata]:
    """
    Get a valid configuration option and its metadata.

    Parameters
    ----------
    option: The configuration option to act on.
    """
    if option in METADATA:
        return option, METADATA[option]
    # attempt to see if the user provided a name directly
    option = option.lower()
    for attr, meta in METADATA.items():
        if isinstance(meta.name, dict):
            name = meta.name.get(inter.locale) or meta.name.get(inter.guild_locale) or meta.name[disnake.Locale.en_GB]
        else:
            name = meta.name
        if option == name.lower():
            return attr, meta

    raise commands.UserInputError("Could not find a configuration option with that name.")


class Configuration(
    commands.Cog,
    name="Config Manager",
    slash_command_attrs={
        "dm_permission": False,
        "default_member_permissions": disnake.Permissions(manage_guild=True),
    },
):
    """Configuration management for each guild."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @commands.Cog.listener("on_guild_remove")
    async def remove_config_on_guild_remove(self, guild: disnake.Guild) -> None:
        """Delete the config as soon as we leave a guild."""
        async with self.bot.db.begin() as session:
            stmt = sa.delete(GuildConfig).where(GuildConfig.id == guild.id, GuildConfig.guild_id == guild.id)
            result = await session.execute(stmt)
            if result.rowcount != 1:
                logger.warning(f"guild config doesn't exist for guild_id {guild.id}")
                return
            await session.commit()
            # also remove it from the cache
            try:
                del self.bot.guild_configs[guild.id]
            except KeyError:
                pass

    def require_bot(self, inter: disnake.Interaction) -> Literal[True]:
        """Raise an error if the bot is required."""
        if inter.guild_id and inter.guild:
            return True

        if not inter.guild_id:
            raise commands.NoPrivateMessage()

        invite = disnake.utils.oauth_url(
            self.bot.user.id,
            disable_guild_select=True,
            guild=disnake.Object(inter.guild_id),
            scopes={"applications.commands", "bot"},
            permissions=self.bot.invite_permissions,
        )
        msg = (
            "This command cannot be used without the full bot in this server.\n"
            f"You can invite the full bot by [clicking here](<{invite}>)."
        )
        raise BotAccountRequired(msg)

    @commands.slash_command()
    async def config(self, inter: disnake.GuildCommandInteraction) -> None:
        """[BETA] Manage per-guild configuration for Monty."""
        pass

    @config.sub_command("set")
    async def set_command(
        self,
        inter: disnake.GuildCommandInteraction,
        option: str,
        value: str,
    ) -> None:
        """
        [BETA] Set the specified config option to the provided value.

        Parameters
        ----------
        option: The configuration option to change.
        value: The new value of the configuration option.
        """
        option_name, metadata = await config_option(inter, option=option)
        config = await self.bot.ensure_guild_config(inter.guild_id)

        old = getattr(config, option_name)

        if metadata.requires_bot:
            self.require_bot(inter)

        try:
            setattr(config, option_name, value)
        except ValueError as e:
            raise commands.UserInputError(
                metadata.status_messages.set_attr_fail.format(name=metadata.name, err=str(e))
            ) from None
        if validator := metadata.validator:
            try:
                if inspect.iscoroutinefunction(validator):
                    value = await validator(inter, value)
                else:
                    value = validator(inter, value)
            except Exception:
                # reset the configuration
                setattr(config, option_name, old)
                raise
        async with self.bot.db.begin() as session:
            config = await session.merge(config)
            await session.commit()

        await inter.send(
            metadata.status_messages.set_attr_success.format(name=metadata.name, old_setting=old, new_setting=value),
            ephemeral=True,
        )

    @config.sub_command("get")
    async def view_command(
        self, inter: disnake.GuildCommandInteraction, option: tuple[str, ConfigAttrMetadata]
    ) -> None:
        """
        [BETA] View the current config for a config option.

        Parameters
        ----------
        The config option see what's currently set.
        """
        config = await self.bot.ensure_guild_config(inter.guild_id)
        option_name, metadata = option
        current = getattr(config, option_name)

        await inter.response.send_message(
            metadata.status_messages.view_attr_success.format(name=metadata.name, current_setting=current),
            ephemeral=True,
        )

    @config.sub_command("unset")
    async def clear_command(
        self, inter: disnake.GuildCommandInteraction, option: tuple[str, ConfigAttrMetadata]
    ) -> None:
        """
        [BETA] Clear/unset the config for a config option.

        Parameters
        ----------
        The config option to unset/change to default.
        """
        option_name, metadata = option
        config = await self.bot.ensure_guild_config(inter.guild_id)
        current = getattr(config, option_name)
        if current is None:
            await inter.response.send_message("This option is already unset.", ephemeral=True)
            return

        try:
            setattr(config, option_name, None)
        except (TypeError, ValueError):
            raise commands.UserInputError("this option is not clearable.") from None

        async with self.bot.db.begin() as session:
            config = await session.merge(config)
            await session.commit()

        await inter.response.send_message(
            metadata.status_messages.clear_attr_success.format(name=metadata.name),
            ephemeral=True,
        )

    @set_command.autocomplete("option")
    @clear_command.autocomplete("option")
    @view_command.autocomplete("option")
    async def config_autocomplete(
        self,
        inter: disnake.CommandInteraction,
        option: str,
    ) -> Union[dict[str, str], list[str]]:
        """Provide autocomplete for config options."""
        # todo: make this better and not like this
        # todo: support non-nullable names (maybe a second autocomplete)
        # (the above are currently not implemented as there is only two options
        # and all of them are nullable)
        options = {}
        for attr, meta in METADATA.items():
            if isinstance(meta.name, str):
                options[meta.name] = attr
                continue
            # get the localised option, fall back to en_GB
            name = meta.name.get(inter.locale) or meta.name.get(inter.guild_locale) or meta.name[disnake.Locale.en_GB]
            options[name] = attr

        return dict(sorted(options.items()))

    @commands.guild_only()
    @commands.command(name="prefix", hidden=True)
    async def show_prefix(self, ctx: commands.Context) -> None:
        """Show the currently set prefix for the guild. To set a prefix, use `/config prefix set`."""
        config = await self.bot.ensure_guild_config(ctx.guild.id)  # type: ignore # checks prevent guild from being None
        components = DeleteButton(ctx.author, initial_message=ctx.message)
        if config.prefix:
            await ctx.send(
                f"The currently set prefix is ``{config.prefix}``",
                allowed_mentions=disnake.AllowedMentions.none(),
                components=components,
            )
            return

        await ctx.send(
            f"There is no set prefix, using the default prefix: ``{self.bot.command_prefix}``", components=components
        )
        return


def setup(bot: Monty) -> None:
    """Add the configuration cog to the bot."""
    bot.add_cog(Configuration(bot))
