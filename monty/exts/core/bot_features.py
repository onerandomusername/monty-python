import asyncio
import itertools
from typing import TYPE_CHECKING, Literal, Union

import disnake
import sqlalchemy as sa
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.database import Feature
from monty.database.guild import Guild
from monty.log import get_logger
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    MaybeFeature = str
    FeatureConverter = str
else:
    from monty.utils.converters import FeatureConverter, MaybeFeature

logger = get_logger(__name__)

FEATURES_PREFIX = "features_"
FEATURE_VIEW_PREFIX = FEATURES_PREFIX + "view_"
"""{FEATURE_VIEW_PREFIX}{feature.name}:1:{guild_to_check}:{show_all_flag}"""
FEATURES_MAIN_LIST = FEATURES_PREFIX + "main_list"
"""{FEATURES_MAIN_LIST}:{feature.name}:{guild_to_check or ''}:{show_all_flag}"""
FEATURES_GLOBAL_TOGGLE = FEATURES_PREFIX + "global_toggle_"
"""{FEATURES_GLOBAL_TOGGLE}:{feature.name}:{guild_to_check or ''}:{'1' if show_all else '0'}"""
FEATURES_GUILD_TOGGLE = FEATURES_PREFIX + "guild_toggle_"
"""{FEATURES_GUILD_TOGGLE}:{feature.name}:{guild_id}:{'1' if show_all else '0'}"""

FEATURES_PAGINATOR_PREFIX = FEATURES_PREFIX + "paginator_"
FEATURES_PER_PAGE = 10


class FeatureManagement(commands.Cog, name="Feature Management"):
    """Management commands for bot features."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self._colours = itertools.cycle(
            (disnake.Colour(x) for x in (constants.Colours.python_yellow, constants.Colours.python_blue))
        )

    @property
    def features(self) -> dict[str, Feature]:
        """Shortcut to the underlying bot's feature dict."""
        return self.bot.features

    def refresh_in_cache(self, feature: Feature) -> None:
        """Replace the item in cache with the same name as the provided feature."""
        self.features[feature.name] = feature

    async def wait_for_confirmation(
        self,
        message_or_inter: disnake.MessageInteraction | disnake.Message,
        content: str,
        *,
        timeout: float = 30,
        confirm_button_text: str = "Confirm",
        deny_button_text: str = "Deny",
        go_back_button: disnake.ui.Button | None = None,
    ) -> Union[tuple[bool, disnake.MessageInteraction, list[disnake.ui.Container]], tuple[None, None, None]]:
        """Wait for the user to provide confirmation, and handle expiration."""
        # ask the user if they want to add this feature
        if isinstance(message_or_inter, disnake.Message):
            content = "### Confirmation Required\n" + content
        components: list = [
            disnake.ui.Container(disnake.ui.TextDisplay(content), accent_colour=disnake.Colour.dark_gold())
        ]
        row = disnake.ui.ActionRow.with_message_components()
        create_button = disnake.ui.Button(style=disnake.ButtonStyle.green, label=confirm_button_text)
        row.append_item(create_button)
        deny_button = disnake.ui.Button(style=disnake.ButtonStyle.red, label=deny_button_text)
        row.append_item(deny_button)
        components[0].children.append(row)
        custom_ids = {x.custom_id for x in row}

        delete_button = DeleteButton(
            message_or_inter.author,
            allow_manage_messages=False,
            initial_message=message_or_inter if isinstance(message_or_inter, disnake.Message) else None,
        )
        if isinstance(message_or_inter, disnake.Message):
            row.insert_item(0, delete_button)

        if isinstance(message_or_inter, disnake.Message):
            sent_msg = await message_or_inter.reply(
                components=components,
                fail_if_not_exists=False,
            )
        elif isinstance(message_or_inter, disnake.MessageInteraction):
            # add a row outside of the container with the go back button
            components.append(disnake.ui.ActionRow(delete_button))
            if go_back_button:
                components[-1].append_item(go_back_button)
            await message_or_inter.response.edit_message(
                components=components,
            )
            sent_msg = message_or_inter.message
        else:
            raise TypeError("message_or_inter must be a Message or MessageInteraction")

        try:
            inter: disnake.MessageInteraction = await self.bot.wait_for(
                "button_click",
                check=lambda itr: itr.component.custom_id in custom_ids
                and itr.message == sent_msg
                and (itr.author.id in self.bot.owner_ids or itr.author.id == self.bot.owner_id),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            if isinstance(message_or_inter, disnake.MessageInteraction):
                return (False, message_or_inter, components)

            try:
                await sent_msg.edit()
            except disnake.HTTPException:
                pass
            return (None, None, None)

        for comp in row:
            comp.disabled = True
        delete_button.disabled = False

        if inter.component.custom_id != create_button.custom_id:
            # don't create the feature, abort it.
            return (False, inter, components)

        return (True, inter, components)

    # commands

    @commands.group(name="features", invoke_without_command=True)
    async def cmd_features(
        self,
        ctx: commands.Context,
        arg: disnake.Guild | disnake.Object | FeatureConverter = None,
        show_all: Literal["all"] | None = None,
    ) -> None:
        """Manage features."""
        guild = None
        if arg is not None:
            if isinstance(arg, (disnake.Guild, disnake.Object)):
                guild = arg
            if isinstance(arg, Feature):
                await self.show_feature(ctx, arg, with_guilds=True)
                return

        await self.cmd_list(ctx, guild=guild, show_all=(show_all == "all"))

    async def set_feature(self, feature: Feature, status: bool | None) -> Feature:
        """Enable the specified feature globally."""
        if not feature:
            raise commands.UserInputError("That feature does not exist.")
        if feature.enabled is status:
            # already set, return early
            return feature

        async with self.bot.db.begin() as session:
            feature = await session.merge(feature)
            feature.enabled = status
            await session.commit()
            self.refresh_in_cache(feature)

        return feature

    async def show_feature(
        self,
        inter: disnake.MessageInteraction | commands.Context,
        feature: Feature,
        *,
        with_guilds: bool = False,
        guild_id: int | None = None,
        show_all: bool = True,
    ) -> None:
        """Show properties of the provided feature."""
        colour = (
            disnake.Colour.green()
            if feature.enabled is True
            else disnake.Colour.greyple() if feature.enabled is None else disnake.Colour.red()
        )
        components: list = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(f"-# **Features » {feature.name}**\n### {feature.name}"),
            )
        ]
        components[-1].children.append(
            disnake.ui.TextDisplay(f"**Rollout**:\n{feature.rollout.name if feature.rollout else 'None'}")
        )

        guild_to_check = guild_id or (inter.guild.id if inter.guild else None)

        if not guild_id or with_guilds:
            async with self.bot.db.begin() as session:
                stmt = sa.select(Guild).where(Guild.feature_ids.any_() == feature.name)
                result = await session.scalars(stmt)
                guilds = result.all()
            guild_names: list[str] = []
            for g in guilds:
                if dis_guild := self.bot.get_guild(g.id):
                    guild_names.append(f"{dis_guild.name} ({g.id})")
                else:
                    guild_names.append(str(g.id))
            guild_names.sort()

            if guild_names:
                text = "**Guilds**\n" + "\n".join(guild_names).strip()
            else:
                text = "**Guilds**\n*No guilds have overrides.*"
            components[-1].children.append(disnake.ui.TextDisplay(text))

        # add a button to give the feature the guild if the feature is using guild overrides
        if feature.enabled is None and guild_to_check:
            guild_has_feature = await self.bot.guild_has_feature(
                guild_to_check,
                feature.name,
                include_feature_status=False,
                create_if_not_exists=False,
            )
            if guild_has_feature:
                colour = disnake.Colour.orange()
            show_all_flag = "1" if show_all else "0"
            components[-1].children.append(
                disnake.ui.Section(
                    disnake.ui.TextDisplay("### Status:"),
                    accessory=disnake.ui.Button(
                        label="Click to disable in Guild" if guild_has_feature else "Click to enable in Guild",
                        style=disnake.ButtonStyle.green if guild_has_feature else disnake.ButtonStyle.grey,
                        custom_id=f"{FEATURES_GUILD_TOGGLE}:{guild_to_check or ''}:{feature.name}:{show_all_flag}",
                    ),
                )
            )
        else:  # otherwise just have a title for the status
            components[-1].children.append(disnake.ui.TextDisplay("### Status:"))

        status_options = {
            True: disnake.SelectOption(
                label="Globally enabled" if feature.enabled is True else "Enable feature globally",
                value="True",
            ),
            False: disnake.SelectOption(
                label="Globally disabled" if feature.enabled is False else "Disable feature globally",
                value="False",
            ),
            None: disnake.SelectOption(
                label="Guild overrides" if feature.enabled is None else "Switch to guild overrides",
                value="None",
            ),
        }

        components[-1].children.append(
            disnake.ui.ActionRow(
                disnake.ui.StringSelect(
                    placeholder=status_options[feature.enabled].label,
                    custom_id=f"{FEATURES_GLOBAL_TOGGLE}:{feature.name}:"
                    f"{guild_to_check or ''}:{'1' if show_all else '0'}",
                    options=[v for k, v in status_options.items() if k != feature.enabled],
                )
            )
        )
        # Try to get the current page from the message's components (if available)
        show_all_flag = "1" if show_all else "0"
        components.append(
            disnake.ui.ActionRow(
                DeleteButton(
                    inter.author,
                    allow_manage_messages=False,
                    initial_message=(inter.message.reference and inter.message.reference.message_id),
                ),
                disnake.ui.Button(
                    emoji="\u21a9",
                    style=disnake.ButtonStyle.secondary,
                    custom_id=f"{FEATURES_MAIN_LIST}:{feature.name}:{guild_to_check or ''}:{show_all_flag}",
                ),
            )
        )

        components[0].accent_colour = colour

        if isinstance(inter, commands.Context):
            await inter.reply(components=components, fail_if_not_exists=False, mention_author=False)
        else:
            await inter.response.edit_message(components=components)

    @commands.Cog.listener("on_button_click")
    async def feature_button_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for feature view buttons."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(FEATURE_VIEW_PREFIX):
            return
        if not await self.bot.is_owner(inter.author):
            await inter.response.send_message("You do not own this bot.", ephemeral=True)
            return
        # this `:` ensures that split won't fail
        custom_id = inter.component.custom_id.removeprefix(FEATURE_VIEW_PREFIX) + "::"
        feature_name, show_guilds, guild_id, show_all_flag, _ = custom_id.split(":", 4)
        show_guilds = bool(show_guilds)
        if guild_id == "":
            guild_id = None
        else:
            guild_id = int(guild_id)
        show_all = show_all_flag == "1"
        feature = self.features.get(feature_name)
        if not feature:
            await inter.response.send_message("That feature does not exist.", ephemeral=True)
            return
        await self.show_feature(
            inter,
            feature,
            with_guilds=show_guilds,
            guild_id=guild_id,
            show_all=show_all,
        )

    @commands.Cog.listener("on_button_click")
    async def features_main_list_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for the main features list button."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(FEATURES_MAIN_LIST):
            return
        if not await self.bot.is_owner(inter.author):
            await inter.response.send_message("You do not own this bot.", ephemeral=True)
            return
        # Parse page and guild_id from custom_id if present
        page = 0
        feature_name = None
        guild_id = None
        parts = inter.component.custom_id.split(":")
        show_all = None
        if len(parts) == 4:
            show_all = parts[3] == "1"
            parts.pop()
        if len(parts) == 3:
            guild_id = int(parts[2]) if parts[2] else None
            parts.pop()
        if len(parts) == 2:
            feature_name = None
            page: int = 0
            try:
                page = int(parts[1])
            except ValueError:
                feature_name = parts[1]

        # Find the page containing the feature if present
        if feature_name:
            features = sorted(self.features.items())
            for idx, (name, _) in enumerate(features):
                if name == feature_name:
                    page = idx // FEATURES_PER_PAGE
                    break
        # If guild_id is present, pass it to _send_features_list
        await self._send_features_list(inter, page=page, for_guild=guild_id, show_all=show_all)

    @commands.Cog.listener("on_button_click")
    async def features_paginator_listener(self, inter: disnake.MessageInteraction) -> None:
        """Handle paginator navigation for features list."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(FEATURES_PAGINATOR_PREFIX):
            return
        if not await self.bot.is_owner(inter.author):
            await inter.response.send_message("You do not own this bot.", ephemeral=True)
            return
        # custom_id: features_paginator_{page}_{max_page}
        _, page, max_page, for_guild, show_all = inter.component.custom_id.split(":")
        page = int(page)
        max_page = int(max_page)
        await self._send_features_list(
            inter,
            page=page,
            max_page=max_page,
            for_guild=int(for_guild) if for_guild else None,
            show_all=show_all == "1",
        )

    async def _send_features_list(
        self,
        ctx: commands.Context | disnake.MessageInteraction,
        page: int = 0,
        max_page: int | None = None,
        *,
        for_guild: disnake.Object | int | None = None,
        show_all: bool | None = None,
    ) -> None:
        def _get_feature_page(
            features: list[tuple[str, Feature]],
            page: int,
            per_page: int = FEATURES_PER_PAGE,
        ) -> list[tuple[str, Feature]]:
            start = page * per_page
            end = start + per_page
            return features[start:end]

        if show_all is None:
            show_all = False

        guild_to_check: int | None = None
        # if guild_to_check isn't set, set it to the current guild if available
        # and enable show_all
        if not for_guild and getattr(ctx, "guild", None):
            for_guild = ctx.guild
            show_all = True

        if for_guild:
            title = "Guild Features"
            guild_to_check = getattr(for_guild, "id", None) or for_guild or getattr(ctx.guild, "id", None)  # type: ignore
            guild_db = await self.bot.ensure_guild(guild_to_check)
            if show_all:
                features = sorted(self.features.items())
            else:
                enabled_features = [f for f in self.features.values() if f.name in guild_db.feature_ids]
                features = sorted((f.name, f) for f in enabled_features)
        else:
            title = "Global Features"
            features = sorted(self.features.items())

        total = len(features)
        if max_page is None:
            max_page = (total - 1) // FEATURES_PER_PAGE
        key_defaults = {
            disnake.ButtonStyle.green: "-# :green_square: Feature force enabled globally",
            disnake.ButtonStyle.secondary: "-# :black_large_square: Feature uses guild overrides",
            disnake.ButtonStyle.danger: "-# :red_square: Feature force disabled globally",
            "\U0001f7e0": "-# :orange_circle: Feature force-enabled in this guild",
            "\U0001f7e1": "-# :yellow_circle: Feature enabled here due to rollouts",
        }
        needed_keys = {}
        components: list = [
            disnake.ui.Container(
                accent_colour=next(self._colours),
            )
        ]
        guild_feature_ids = []
        if guild_to_check:
            guild = await self.bot.ensure_guild(guild_to_check)
            guild_feature_ids = guild.feature_ids
            check_guild = True
        else:
            check_guild = False

        page_features = features
        if total >= FEATURES_PER_PAGE:
            page_features = _get_feature_page(features, page, FEATURES_PER_PAGE)

        # Determine if a guild_id should be included in the feature view button
        show_all_flag = "1" if show_all else "0"
        if page_features:
            for _, feature in page_features:
                if feature.enabled is True:
                    button_style = disnake.ButtonStyle.green
                    guild_status = "\U0001f7e2"  # green circle
                elif feature.enabled is None:
                    button_style = disnake.ButtonStyle.gray
                    guild_status = "\U000026ab"  # black circle
                else:
                    button_style = disnake.ButtonStyle.danger
                    guild_status = "\U0001f534"  # red circle

                if check_guild:
                    if feature.name in guild_feature_ids:
                        guild_status = "\U0001f7e0"  # orange circle
                    elif await self.bot.guild_has_feature(guild_to_check, feature.name, include_feature_status=False):
                        guild_status = "\U0001f7e1"  # yellow circle

                if button_style not in needed_keys:
                    needed_keys[button_style] = key_defaults[button_style]
                if guild_status in key_defaults and guild_status not in needed_keys:
                    needed_keys[guild_status] = key_defaults[guild_status]

                components[-1].children.append(
                    disnake.ui.Section(
                        f"{feature.name}",
                        accessory=disnake.ui.Button(
                            emoji=guild_status,
                            style=button_style,
                            custom_id=(
                                f"{FEATURE_VIEW_PREFIX}{feature.name}:1:{guild_to_check}:{show_all_flag}"
                                if guild_to_check
                                else f"{FEATURE_VIEW_PREFIX}{feature.name}:1:::"
                            ),
                        ),
                    )
                )
        # we are here because there are no features
        else:
            if guild_to_check:
                components[-1].children.append(
                    disnake.ui.TextDisplay(f"No features are overridden for {guild_to_check}")
                )
            else:
                components[-1].children.append(disnake.ui.TextDisplay("No features are overridden."))

        # Paginator buttons
        if total >= FEATURES_PER_PAGE:
            paginator_row = disnake.ui.ActionRow()
            show_all_flag = "1" if show_all else "0"
            # Only two pages: show back/forward
            if max_page == 1:
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u25c0",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(f"{FEATURES_PAGINATOR_PREFIX}:0:{max_page}:{guild_to_check or ''}:{show_all_flag}"),
                        disabled=(page == 0),
                    )
                )
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u25b6",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(f"{FEATURES_PAGINATOR_PREFIX}:1:{max_page}:{guild_to_check or ''}:{show_all_flag}"),
                        disabled=(page == max_page),
                    )
                )
            else:
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u23ee",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(f"{FEATURES_PAGINATOR_PREFIX}:0:{max_page}:{guild_to_check or ''}:{show_all_flag}"),
                        disabled=(page == 0),
                    )
                )
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u25c0",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(
                            f"{FEATURES_PAGINATOR_PREFIX}:{max(page - 1, 0)}:"
                            f"{max_page}:{guild_to_check or ''}:{show_all_flag}"
                        ),
                        disabled=(page == 0),
                    )
                )
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u25b6",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(
                            f"{FEATURES_PAGINATOR_PREFIX}:{min(page + 1, max_page)}:"
                            f"{max_page}:{guild_to_check or ''}:{show_all_flag}"
                        ),
                        disabled=(page == max_page),
                    )
                )
                paginator_row.append_item(
                    disnake.ui.Button(
                        emoji="\u23ed",
                        style=disnake.ButtonStyle.secondary,
                        custom_id=(
                            f"{FEATURES_PAGINATOR_PREFIX}:{max_page}:{max_page}:{guild_to_check or ''}:{show_all_flag}"
                        ),
                        disabled=(page == max_page),
                    )
                )
            components[-1].children.append(paginator_row)
            # Page count display
            components[-1].children.append(disnake.ui.TextDisplay(f"Page {page + 1} of {max_page + 1}"))

        components.append(
            disnake.ui.ActionRow(
                DeleteButton(ctx.author, allow_manage_messages=False, initial_message=getattr(ctx, "message", None)),
            ),
        )
        if guild_to_check:
            ## add a button to toggle between showing all features and only guild-enabled features
            components[-1].append_item(
                disnake.ui.Button(
                    label="Show all features" if not show_all else "Show guild features",
                    style=disnake.ButtonStyle.grey,
                    custom_id=f"{FEATURES_MAIN_LIST}:{page}:{guild_to_check or ''}:{'1' if not show_all else '0'}",
                ),
            )

        components[0].children.insert(
            0,
            disnake.ui.TextDisplay(
                f"## {title}\n"
                + "\n".join(needed_keys[key] for key in needed_keys if isinstance(key, disnake.ButtonStyle))
                + (
                    ("\n" + "\n".join(needed_keys[key] for key in needed_keys if isinstance(key, str)))
                    if any(isinstance(key, str) for key in needed_keys)
                    else ""
                )
            ),
        )
        if isinstance(ctx, disnake.MessageInteraction):
            await ctx.response.edit_message(components=components)
        else:
            await ctx.reply(components=components, fail_if_not_exists=False, mention_author=False)

    async def cmd_list(
        self,
        ctx: commands.Context | disnake.MessageInteraction,
        guild: disnake.Guild | disnake.Object | None = None,
        show_all: bool = False,
    ) -> None:
        """
        List all existing features, or features enabled in a specific guild if provided.

        If show_all is True, show all features even if guild is set.
        """
        await self._send_features_list(ctx, for_guild=guild, show_all=show_all)

    # guild commands

    @cmd_features.command(name="guild")
    async def cmd_guild(
        self,
        ctx: commands.Context,
    ) -> None:
        """Show the features for the current guild."""
        await self.cmd_features(ctx, arg=ctx.guild)

    @cmd_features.command(name="add", aliases=("a", "enable"), require_var_positional=True)
    async def cmd_guild_add(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[Union[disnake.Guild, disnake.Object]] = None,  # type: ignore
        *names: MaybeFeature,
    ) -> None:
        """Add the features to the provided guilds, defaulting to the local guild."""
        if not guilds or guilds is None:
            guilds: list[disnake.Guild] = [ctx.guild]  # type:ignore

        # only give feature create option if there is only one feature
        ctx_or_inter: Union[disnake.MessageInteraction, commands.Context[Monty]] = ctx
        async with self.bot.db.begin() as session:
            if len(names) == 1:
                name = names[0]
                feature = self.features.get(name)

                if not feature:
                    confirmed, inter, components = await self.wait_for_confirmation(
                        ctx.message,
                        f"The feature `{name}` does not exist. Would you like to create it?\n\u200b",
                        timeout=30,
                        confirm_button_text="Create feature",
                        deny_button_text="Abort",
                    )
                    if confirmed is None or inter is None:
                        # we timed out, and this was taken care of in the above method.
                        return
                    if not confirmed:
                        await inter.response.edit_message(content="Aborting.", components=components)
                        return

                    # defer just in case the database calls take a bit long
                    await inter.response.defer()

                    # replace ctx with the interaction for the next response
                    ctx_or_inter = inter

                    feature = Feature(name)
                    session.add(feature)
                    self.refresh_in_cache(feature)
                feature_names = [feature.name]
            else:
                # there were more than 1 provided features here
                invalids = []
                feature_names: list[str] = []
                for name in names:
                    feature = self.features.get(name)
                    if feature is not None:
                        feature_names.append(feature.name)
                    else:
                        invalids.append(name)
                if invalids:
                    raise commands.UserInputError(
                        "One or more of the provided features do not exist: `" + "`, `".join(invalids) + "`."
                    )
            guild_dbs: list[Guild] = []
            for guild in guilds:
                guild_db = await self.bot.ensure_guild(guild.id)
                guild_dbs.append(guild_db)

                more_features = []
                for name in feature_names:
                    if name in guild_db.feature_ids:
                        if len(guilds) == 1:
                            raise commands.UserInputError(f"That feature is already enabled in guild ID `{guild.id}`.")
                        else:
                            continue
                    more_features.append(name)
                guild_db.feature_ids.extend(more_features)
                guild_db = await session.merge(guild_db)
                # refresh the cache after the merge
                self.bot.guild_db[guild.id] = guild_db

        button = DeleteButton(ctx_or_inter.author, allow_manage_messages=False, initial_message=ctx.message)
        if isinstance(ctx_or_inter, disnake.Interaction):
            method = ctx_or_inter.edit_original_message
        else:
            method = ctx.reply
        await method(
            f"Added guild IDs `{'`, `'.join(str(g.id) for g in guilds)}` "
            f"to the following features: `{'`, `'.join(sorted(feature_names))}`.",
            components=button,
        )

    @cmd_features.command(name="remove", aliases=("r", "disable"), require_var_positional=True)
    async def cmd_guild_remove(
        self,
        ctx: commands.Context,
        guilds: commands.Greedy[Union[disnake.Guild, disnake.Object]] = None,  # type: ignore
        *names: MaybeFeature,
    ) -> None:
        """Remove the features from the provided guilds, defaulting to the local guild."""
        if not guilds or guilds is None:
            guilds: list[disnake.Guild] = [ctx.guild]  # type:ignore

        invalids = []
        feature_names: list[str] = []
        for name in names:
            feature = self.features.get(name)
            if feature is not None:
                feature_names.append(feature.name)
            else:
                invalids.append(name)
        if invalids:
            raise commands.UserInputError(
                "One or more of the provided features do not exist: `" + "`, `".join(invalids) + "`."
            )

        guild_dbs: list[Guild] = []
        async with self.bot.db.begin() as session:
            for guild in guilds:
                guild_db = await self.bot.ensure_guild(guild.id)
                guild_dbs.append(guild_db)

                remove_features = []
                for name in feature_names:
                    if name not in guild_db.feature_ids:
                        if len(guilds) == 1:
                            raise commands.UserInputError(f"That feature is not enabled in guild ID `{guild.id}`.")
                        else:
                            continue
                    remove_features.append(name)
                for feature in remove_features:
                    guild_db.feature_ids.remove(feature)
                guild_db = await session.merge(guild_db)
            await session.commit()

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.reply(
            f"Removed guild IDs `{'`, `'.join(str(g.id) for g in guilds)}` "
            f"from the following features: `{'`, `'.join(sorted(feature_names))}`.",
            components=button,
        )

    @commands.Cog.listener(disnake.Event.dropdown)
    async def FEATURES_GLOBAL_TOGGLE_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for guild feature toggle select."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(FEATURES_GLOBAL_TOGGLE):
            return
        if not await self.bot.is_owner(inter.author):
            await inter.response.send_message("You do not own this bot.", ephemeral=True)
            return
        # Parse custom_id: FEATURES_GLOBAL_TOGGLE:feature_name:guild_id:show_all_flag
        _, feature_name, guild_id, show_all_flag = inter.component.custom_id.split(":", 3)
        show_all = show_all_flag == "1"
        feature = self.features.get(feature_name)
        if not feature:
            await inter.response.send_message("That feature does not exist.", ephemeral=True)
            return

        selected_value = inter.values[0] if hasattr(inter, "values") and inter.values else None
        if selected_value not in ("True", "False", "None"):
            await inter.response.send_message("Invalid selection.", ephemeral=True)
            return

        # Ask for confirmation
        action_map = {"True": "globally enable", "False": "globally disable", "None": "switch to guild overrides"}
        confirm, conf_inter, components = await self.wait_for_confirmation(
            inter,
            f"-# **Features » {feature.name} » global enablement confirmation**\n ### Confirmation Required\nAre you"
            f" sure you want to **{action_map[selected_value]}** feature `{feature_name}`?\n\u200b",
            go_back_button=disnake.ui.Button(
                emoji="\u21a9",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"{FEATURE_VIEW_PREFIX}{feature.name}:1:{guild_id}:{'1' if show_all else '0'}",
            ),
        )
        if confirm is None or conf_inter is None:
            return
        if confirm:
            # Update feature.enabled accordingly
            feature = await self.set_feature(feature, None if selected_value == "None" else selected_value == "True")

        # Show features again to return to display
        await self.show_feature(
            conf_inter,
            feature,
            with_guilds=True,
            guild_id=int(guild_id) if guild_id else None,
            show_all=show_all,
        )

    @commands.Cog.listener("on_button_click")
    async def guild_feature_toggle_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for guild feature toggle button."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(f"{FEATURES_GUILD_TOGGLE}"):
            return
        if not await self.bot.is_owner(inter.author):
            await inter.response.send_message("You do not own this bot.", ephemeral=True)
            return
        _, guild_id, feature_name, show_all_flag = inter.component.custom_id.split(":", 3)
        feature = self.features.get(feature_name)
        if not feature:
            await inter.response.send_message("That feature does not exist.", ephemeral=True)
            return

        guild_id = int(guild_id)
        show_all = show_all_flag == "1"
        guild = self.bot.get_guild(guild_id)
        if not guild:
            await inter.response.send_message("Guild not found.", ephemeral=True)
            return

        guild_has_feature = await self.bot.guild_has_feature(
            guild, feature.name, include_feature_status=False, create_if_not_exists=False
        )

        async with self.bot.db.begin() as session:
            guild_db = await self.bot.ensure_guild(guild.id)
            if not guild_has_feature:
                if feature.name not in guild_db.feature_ids:
                    guild_db.feature_ids.append(feature.name)
            else:
                if feature.name in guild_db.feature_ids:
                    guild_db.feature_ids.remove(feature.name)
            guild_db = await session.merge(guild_db)
            self.bot.guild_db[guild.id] = guild_db
            await session.commit()

        await self.show_feature(
            inter,
            feature,
            with_guilds=True,
            guild_id=guild_id,
            show_all=show_all,
        )

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Require all commands in this cog are by the bot author and are in guilds."""
        if await self.bot.is_owner(ctx.author):
            return True

        raise commands.NotOwner("You do not own this bot.")


def setup(bot: Monty) -> None:
    """Add the FeatureManagement cog to the bot."""
    bot.add_cog(FeatureManagement(bot))
