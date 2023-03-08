from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Final, Literal, Optional, TypedDict, Union

import aiohttp
import disnake
import tomli
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.database import GuildConfig
from monty.errors import BotAccountRequired
from monty.log import get_logger
from monty.utils.messages import DeleteButton


GITHUB_REQUEST_HEADERS = {}
if GITHUB_TOKEN := constants.Tokens.github:
    GITHUB_REQUEST_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

logger = get_logger(__name__)

if TYPE_CHECKING:
    from typing_extensions import NotRequired


class ConfigMetadataDict(TypedDict):
    """The dict of data for ConfigMetadata."""

    name: str
    description: str
    nullable: bool
    success_message: str
    success_clear_message: str
    show_message: str
    null_show_message: NotRequired[str]
    validation_error_message: str
    require_bot: bool
    ephemeral: NotRequired[bool]


@dataclass
class ConfigMetadata:
    """Dataclass for configuration metadata."""

    name: str
    description: str
    nullable: bool
    success_message: str
    success_clear_message: str
    show_message: str
    validation_error_message: str
    require_bot: bool
    null_show_message: Optional[str] = None
    ephemeral: bool = True


class Configuration(
    commands.Cog,
    name="Config Manager",
    slash_command_attrs={"dm_permission": False, "default_member_permissions": disnake.Permissions(manage_guild=True)},
):
    """Configuration management for each guild."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.valid_fields: Final[Dict[str, dataclasses.Field[Any]]] = {
            field.name: field for field in dataclasses.fields(GuildConfig)
        }
        self.load_schema()

    def load_schema(self) -> None:
        """Load the configuration strings from the configuration file."""
        with open("monty/config_schema.toml", "rb") as f:
            config = tomli.load(f)
        meta: dict[str, Any] = config["meta"]  # noqa: F841
        schema: dict[str, ConfigMetadataDict] = config["schema"]

        self.schema: dict[str, ConfigMetadata] = {}
        for table, data in schema.items():
            if table not in self.valid_fields:
                raise RuntimeError("the config_schema.toml is invalid.")
            self.schema[table] = ConfigMetadata(**data)

        self.name_to_option = {s.name: k for k, s in self.schema.items()}

        logger.info("Loaded the config schema.")

    @commands.Cog.listener("on_guild_remove")
    async def remove_config_on_guild_remove(self, guild: disnake.Guild) -> None:
        """Delete the config as soon as we leave a guild."""
        async with self.bot.db.begin() as session:
            config = GuildConfig(id=guild.id, guild_id=guild.id)
            await session.delete(config)
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
            "This command cannot be used without the bot, as the bot must be here to listen for prefixed commands.\n"
            f"You can invite the full bot by [clicking here](<{invite}>)."
        )
        raise BotAccountRequired(msg)

    @commands.slash_command()
    async def config(self, inter: disnake.GuildCommandInteraction) -> None:
        """[ALPHA] Manage per-guild configuration for Monty."""
        pass

    @config.sub_command("set")
    async def set_command(
        self,
        inter: disnake.GuildCommandInteraction,
        option: str,
        value: str,
    ) -> None:
        """
        Set the specified option to the specifed value.

        Parameters
        ----------
        option: the configuration option to set.
        value: the new value of the configuration option.
        """
        config = await self.bot.ensure_guild_config(inter.guild_id)

        if option in self.name_to_option:
            option = self.name_to_option[option]
        if option not in self.valid_fields:
            raise commands.UserInputError("option must be a valid configuration item (see autocomplete)")

        field = self.valid_fields[option]

        old = getattr(config, field.name)
        schema = self.schema[field.name]

        if schema.require_bot:
            self.require_bot(inter)

        try:
            setattr(config, field.name, value)
        except ValueError:
            raise commands.UserInputError(schema.validation_error_message.format(new=value)) from None
        try:
            # special config for github_issues_org
            if option == "github_issues_org":
                try:
                    async with self.bot.http_session.head(
                        f"https://github.com/{value}", headers=GITHUB_REQUEST_HEADERS, raise_for_status=True
                    ):
                        pass
                except aiohttp.ClientResponseError:
                    raise commands.UserInputError("organisation must be a valid github user or organsation.") from None

        except Exception:
            # reset the configuration
            setattr(config, field.name, old)
            raise
        async with self.bot.db.begin() as session:
            config = await session.merge(config)
            await session.commit()

        await inter.send(schema.success_message.format(new=value), ephemeral=schema.ephemeral)

    @config.sub_command("view")
    async def view_command(self, inter: disnake.GuildCommandInteraction, option: str) -> None:
        """
        View the current config for a config option.

        Parameters
        ----------
        The config option to view the currently set item.
        """
        config = await self.bot.ensure_guild_config(inter.guild_id)
        if option in self.name_to_option:
            option = self.name_to_option[option]
        if option not in self.valid_fields:
            raise commands.UserInputError("option must be a valid configuration item (see autocomplete)")
        field = self.valid_fields[option]
        current = getattr(config, field.name)
        schema = self.schema[field.name]

        if current is not None:
            await inter.response.send_message(schema.show_message.format(current=current), ephemeral=True)
        else:
            await inter.response.send_message(schema.null_show_message, ephemeral=True)

    @config.sub_command("clear")
    async def clear_command(self, inter: disnake.GuildCommandInteraction, option: str) -> None:
        """
        Clear the config for a config option.

        Parameters
        ----------
        The config option to clear.
        """
        config = await self.bot.ensure_guild_config(inter.guild_id)
        if option in self.name_to_option:
            option = self.name_to_option[option]
        if option not in self.valid_fields:
            raise commands.UserInputError("option must be a valid configuration item (see autocomplete)")

        field = self.valid_fields[option]
        current = getattr(config, field.name)
        schema = self.schema[field.name]
        if current is None:
            await inter.response.send_message("This option is already unset.", ephemeral=True)
            return

        try:
            setattr(config, field.name, None)
        except (TypeError, ValueError):
            raise commands.UserInputError("this option is not clearable.") from None

        async with self.bot.db.begin() as session:
            config = await session.merge(config)
            await session.commit()

        await inter.response.send_message(schema.success_clear_message, ephemeral=True)

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
        return self.name_to_option

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
