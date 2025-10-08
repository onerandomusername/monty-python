import itertools
from collections import defaultdict
from typing import Literal

import disnake
import sqlalchemy as sa
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.config import (
    GROUP_TO_ATTR,
    METADATA,
    Category,
    ConfigAttrMetadata,
    SelectGroup,
)
from monty.config import (
    get_category_choices as _get_category_choices,
)
from monty.database import GuildConfig
from monty.errors import BotAccountRequired
from monty.log import get_logger
from monty.utils.messages import DeleteButton


logger = get_logger(__name__)


def get_locale_from_dict(
    locales: disnake.Locale | list[disnake.Locale | Literal[None]],
    table: dict[disnake.Locale | Literal["_"], str],
) -> str:
    """Get the first string out of table that matches a locale. Defaults to en_GB if no locale can be found."""
    if isinstance(locales, disnake.Locale):
        locales = [locales]
    for locale in locales:
        if locale in table:
            return table[locale]
    return table[disnake.Locale.en_GB]


def get_localised_response(
    inter: disnake.ApplicationCommandInteraction | disnake.ModalInteraction | disnake.MessageInteraction,
    text: str,
    **kwargs: dict[disnake.Locale | Literal["_"], str] | str,
) -> str:
    """For the provided string, add the correct localised option names based on the interaction's locales."""
    for name, content in kwargs.items():
        if isinstance(content, dict):
            content = get_locale_from_dict([inter.locale, inter.guild_locale], content)
            kwargs[name] = content

    return text.format(**kwargs)


async def can_guild_set_config_option(bot: Monty, *, metadata: ConfigAttrMetadata, guild_id: int) -> bool:
    """Returns True if the configuration option is settable, False if a feature is required."""
    if metadata.depends_on_features:
        for feature in metadata.depends_on_features:
            if not await bot.guild_has_feature(guild_id, feature, create_if_not_exists=False):
                return False
    return True


class Configuration(
    commands.Cog,
    name="Guild Config",
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
        "default_member_permissions": disnake.Permissions(manage_guild=True),
    },
):
    """Configuration management for each guild."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self._colours = itertools.cycle(
            disnake.Colour(x) for x in (constants.Colours.python_yellow, constants.Colours.python_blue)
        )

    @commands.Cog.listener("on_guild_remove")
    async def remove_config_on_guild_remove(self, guild: disnake.Guild) -> None:
        """Delete the config as soon as we leave a guild."""
        async with self.bot.db.begin() as session:
            stmt = sa.delete(GuildConfig).where(GuildConfig.id == guild.id, GuildConfig.guild_id == guild.id)
            result = await session.execute(stmt)
            if result.rowcount != 1:
                logger.info(f"guild config doesn't exist for guild_id {guild.id}")
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

    async def _send_categories(self, inter: disnake.ApplicationCommandInteraction) -> None:
        sections = [
            disnake.ui.Section(
                disnake.ui.TextDisplay(
                    get_localised_response(
                        inter,
                        "### {data}\n{description}",
                        data=cat.value.name,
                        description=cat.value.description or "",
                    )
                ),
                accessory=disnake.ui.Button(
                    label="Edit",
                    emoji=cat.value.emoji,
                    style=cat.value.button.style,
                    custom_id=f"config:v1:category:{cat.name}:{inter.author.id}",
                ),
            )
            for cat in Category
        ]

        msg_components: list[disnake.ui.Container | disnake.ui.ActionRow | disnake.ui.TextDisplay] = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    get_localised_response(
                        inter,
                        "## Configuration\nSelect a category below to view and edit the configuration options in that"
                        " category.",
                    )
                ),
                disnake.ui.Separator(divider=False),
                *sections,
                accent_colour=next(self._colours),
            ),
        ]
        msg_components.append(
            disnake.ui.ActionRow(DeleteButton(inter.author)),
        )
        await inter.response.send_message(components=msg_components)

    async def _send_category_options(
        self,
        inter: disnake.ApplicationCommandInteraction | disnake.MessageInteraction | disnake.ModalInteraction,
        category: Category,
        current_config: GuildConfig | None = None,
    ) -> None:
        category_options = {attr: meta for attr, meta in METADATA.items() if category in meta.categories}
        select_group_options: defaultdict[SelectGroup, list[disnake.SelectOption]] = defaultdict(list)
        positioning = {}
        for attr, meta in tuple(category_options.items()):
            if not await can_guild_set_config_option(
                self.bot,
                metadata=category_options[attr],
                guild_id=inter.guild_id,  # type: ignore
            ):
                continue

            if meta.select_option:
                default = bool(current_config and getattr(current_config, attr))
                name = get_localised_response(inter, "{data}", data=meta.name)
                select_group_options[meta.select_option.group].append(
                    meta.get_select_option(default=default, locale=inter.locale, attr=attr)
                )

            if meta.select_option:
                if meta.select_option.group not in positioning:
                    positioning[meta.select_option.group] = 0
            else:
                positioning[attr] = 1

        components: list[disnake.ui.ActionRow | disnake.ui.TextDisplay] = []
        modalable_components = []
        for attr_or_group in positioning:
            nested_components = []
            ## handle select groups
            if isinstance(attr_or_group, SelectGroup):
                select_group = attr_or_group
                options = select_group_options.get(select_group, [])
                if not options:
                    continue
                preceding_text = ""
                supertext = ""
                if select_group.value.supertext:
                    supertext = get_localised_response(inter, "{data}", data=select_group.value.supertext)
                    preceding_text += "### " + supertext + "\n"
                if select_group.value.description:
                    description = get_localised_response(inter, "{data}", data=select_group.value.description)
                    preceding_text += description + "\n"
                if preceding_text:
                    nested_components.append(disnake.ui.TextDisplay(preceding_text.strip()))
                placeholder = get_localised_response(inter, "{data}", data=select_group.value.placeholder)
                select = disnake.ui.Select(
                    placeholder=placeholder,
                    options=options,
                    min_values=0,
                    max_values=len(options),
                    custom_id=f"config:v1:select:{attr_or_group.name}:{inter.author.id}",
                    required=False,
                )
                modalable_components.append(
                    disnake.ui.Label(get_localised_response(inter, "{data}", data=supertext), select)
                )
                nested_components.append(disnake.ui.ActionRow(select))
                if select_group.value.subtext:
                    subtext = get_localised_response(inter, "{data}", data=select_group.value.subtext)
                    nested_components.append(disnake.ui.TextDisplay(subtext))
            ## handle button for modal
            elif isinstance(attr_or_group, str):
                attr = attr_or_group
                meta = category_options[attr]
                if not meta.modal:
                    continue
                if not await can_guild_set_config_option(
                    self.bot,
                    metadata=category_options[attr],
                    guild_id=inter.guild_id,  # type: ignore
                ):
                    continue
                if current_config:
                    current = getattr(current_config, attr)
                else:
                    current = None
                name = get_localised_response(inter, "{data}", data=meta.name)
                modalable_components.append(
                    meta.get_text_input(custom_id=attr, name=name, current=current, locale=inter.locale)
                )
                components.extend(
                    (
                        disnake.ui.TextDisplay(
                            content="### " + name,
                        ),
                        disnake.ui.ActionRow(
                            disnake.ui.Button(
                                style=meta.modal.button_style(current),
                                emoji=meta.emoji,
                                label=get_localised_response(inter, "{data}", data=meta.modal.button_label),
                                custom_id=f"config:v1:edit:{attr}:{inter.author.id}",
                            )
                        ),
                    )
                )

            if nested_components:
                components.extend(nested_components)

        if not components:
            raise RuntimeError("No configuration options found for this category.")

        if len(modalable_components) <= 5:
            await inter.response.send_modal(
                title=f"Edit {category.value.name} Settings",
                custom_id=f"config:v1:modal:{category.name}:{inter.author.id}",
                components=modalable_components,
            )
            return
        msg_components: list[disnake.ui.Container | disnake.ui.ActionRow | disnake.ui.TextDisplay] = [
            disnake.ui.Container(
                *components,
                accent_colour=next(self._colours),
            ),
        ]
        msg_components.append(
            disnake.ui.ActionRow(
                DeleteButton(inter.author),
            ),
        )
        await inter.response.send_message(components=msg_components)

    @commands.slash_command()
    async def config(
        self,
        inter: disnake.GuildCommandInteraction,
        category_name: str | None = commands.Param(
            default=None,
            name="category",  # noqa: B008
            description="Choose a configuration category to view the options in that category.",
            choices=_get_category_choices(),
        ),
    ) -> None:
        """[BETA] Manage per-guild configuration for Monty."""
        if not category_name:
            await self._send_categories(inter)
            return

        category: Category = Category[category_name]
        config = await self.bot.ensure_guild_config(inter.guild_id)
        await self._send_category_options(inter, category, current_config=config)
        return

    @commands.command(name="prefix", hidden=True)
    async def show_prefix(self, ctx: commands.Context) -> None:
        """Show the currently set prefix for the guild. To set a prefix, use `/config prefix set`."""
        if not ctx.guild:
            await ctx.send(f"The prefix in DMs is ``{self.bot.command_prefix}``")
            return
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

    @commands.Cog.listener(disnake.Event.button_click)
    async def process_category_clicks(self, inter: disnake.MessageInteraction) -> None:
        """Handle button clicks for configuration modals."""
        if not inter.data.custom_id.startswith("config:v1:category:"):
            return

        parts = inter.data.custom_id.removeprefix("config:v1:category:")
        if len(parts.split(":")) != 2:
            return
        category_name, author_id = parts.split(":")
        if str(inter.author.id) != author_id:
            await inter.response.send_message(
                "You cannot interact with this button as you did not initiate this interaction.",
                ephemeral=True,
            )
            return
        try:
            category = Category[category_name]
        except KeyError:
            await inter.response.send_message("This configuration category no longer exists.", ephemeral=True)
            return
        config = await self.bot.ensure_guild_config(inter.guild_id)  # type: ignore # checks prevent guild from being None
        await self._send_category_options(inter, category, current_config=config)

    async def _process_set_modal(self, inter: disnake.ModalInteraction) -> None:
        """Handle modal submissions for configuration options."""
        if not inter.data.custom_id.startswith("config:v1:modal:"):
            return
        if not inter.guild_id:
            await inter.response.send_message(
                "Configuration can only be used in a guild.",
                ephemeral=True,
            )
            return

        parts = inter.data.custom_id.removeprefix("config:v1:modal:")
        if len(parts.split(":")) != 2:
            return
        category_name, author_id = parts.split(":")
        if str(inter.author.id) != author_id:
            raise commands.CheckFailure("You cannot interact with this modal as you did not initiate this interaction.")
        try:
            category = Category[category_name]
        except KeyError:
            raise commands.UserInputError("This configuration category no longer exists.") from None
        config = await self.bot.ensure_guild_config(inter.guild_id)  # type: ignore # checks prevent guild from being None

        updates = {}
        for custom_id, value in inter.values.items():
            if custom_id not in METADATA:
                if not custom_id.startswith("config:v1:select:"):
                    continue
                custom_id = custom_id.removeprefix("config:v1:select:")
                try:
                    group_name, _author = custom_id.split(":")
                except ValueError:
                    continue
                if group_name not in SelectGroup.__members__:
                    continue
                groups = GROUP_TO_ATTR.get(SelectGroup[group_name], [])
                if not groups:
                    continue
                for attr in groups:
                    meta = METADATA[attr]
                    if category not in meta.categories:
                        continue
                    parsed_value = bool(attr in value)
                    if parsed_value and not await can_guild_set_config_option(
                        self.bot, metadata=meta, guild_id=inter.guild_id
                    ):  # type: ignore
                        raise commands.CheckFailure(
                            "You cannot set this configuration option as"
                            " your guild does not have the required feature(s).",
                        )
                    updates[attr] = parsed_value
                continue
            meta = METADATA[custom_id]
            if category not in meta.categories:
                continue
            if not await can_guild_set_config_option(self.bot, metadata=meta, guild_id=inter.guild_id):  # type: ignore
                raise commands.CheckFailure(
                    "You cannot set this configuration option as your guild does not have the required feature(s).",
                )
            parsed_value = value
            updates[custom_id] = parsed_value
            if meta.validator:
                if not await meta.validator(inter, parsed_value):  # type: ignore
                    raise commands.UserInputError(
                        get_localised_response(
                            inter,
                            "The value provided for **{option}** is not valid. Please check the value and try again.",
                            option=get_localised_response(inter, "{data}", data=meta.name),
                        )
                    )
        if not updates:
            raise commands.UserInputError("No valid configuration options were provided.")

        async with self.bot.db.begin() as session:
            for attr, value in updates.items():
                setattr(config, attr, value)
            await session.merge(config)
            await session.commit()

        await inter.response.send_message(
            f"Successfully updated the configuration for the **{category.value.name}** category.",
            ephemeral=True,
        )

    @commands.Cog.listener(disnake.Event.modal_submit)
    async def process_set_modal(self, inter: disnake.ModalInteraction) -> None:
        """
        Process a modal interaction for setting configuration options.

        Catches errors and sends them to the error handler.
        """
        try:
            await self._process_set_modal(inter)
        except Exception as e:
            self.bot.dispatch("modal_error", inter, e)


def setup(bot: Monty) -> None:
    """Add the configuration cog to the bot."""
    bot.add_cog(Configuration(bot))
