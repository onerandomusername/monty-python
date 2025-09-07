import asyncio
import textwrap
from typing import TYPE_CHECKING, Union

import disnake
import sqlalchemy as sa
from disnake.ext import commands

from monty.bot import Monty
from monty.database import Feature
from monty.database.guild import Guild
from monty.log import get_logger
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    MaybeFeature = str
else:
    from monty.utils.converters import MaybeFeature

logger = get_logger(__name__)

FEATURE_VIEW_PREFIX = "feature_view_"
FEATURES_MAIN_LIST = "features_main_list"


class FeatureManagement(commands.Cog, name="Feature Management"):
    """Management commands for bot features."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @property
    def features(self) -> dict[str, Feature]:
        """Shortcut to the underlying bot's feature dict."""
        return self.bot.features

    def refresh_in_cache(self, feature: Feature) -> None:
        """Replace the item in cache with the same name as the provided feature."""
        self.features[feature.name] = feature

    async def wait_for_confirmation(
        self,
        message: disnake.Message,
        content: str,
        *,
        timeout: float = 30,
        confirm_button_text: str = "Confirm",
        deny_button_text: str = "Deny",
    ) -> Union[tuple[bool, disnake.MessageInteraction, disnake.ui.MessageActionRow], tuple[None, None, None]]:
        """Wait for the user to provide confirmation, and handle expiration."""
        # ask the user if they want to add this feature
        components = disnake.ui.ActionRow.with_message_components()
        create_button = disnake.ui.Button(style=disnake.ButtonStyle.green, label=confirm_button_text)
        components.append_item(create_button)
        deny_button = disnake.ui.Button(style=disnake.ButtonStyle.red, label=deny_button_text)
        components.append_item(deny_button)
        custom_ids = {x.custom_id for x in components}

        delete_button = DeleteButton(message.author, allow_manage_messages=False, initial_message=message)
        components.insert_item(0, delete_button)
        delete_button.disabled = True

        sent_msg = await message.reply(
            content,
            components=components,
            fail_if_not_exists=False,
        )
        try:
            inter: disnake.MessageInteraction = await self.bot.wait_for(
                "button_click",
                check=lambda itr: itr.component.custom_id in custom_ids and itr.message == sent_msg,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            for comp in components:
                comp.disabled = True
            delete_button.disabled = False
            try:
                await sent_msg.edit(content="Timed out.", components=components)
            except disnake.HTTPException:
                pass
            return (None, None, None)

        for comp in components:
            comp.disabled = True
        delete_button.disabled = False

        if inter.component.custom_id != create_button.custom_id:
            # don't create the feature, abort it.
            return (False, inter, components)

        return (True, inter, components)

    # commands

    @commands.group(name="features", invoke_without_command=True)
    async def cmd_features(self, ctx: commands.Context) -> None:
        """Manage features."""
        await self.cmd_list(ctx)

    # feature global state commands

    @cmd_features.group(name="global", invoke_without_command=True)
    async def cmd_global(self, ctx: commands.Context) -> None:
        """Manage the global settings of features."""
        await self.cmd_list(ctx)

    @cmd_global.command(name="enable")
    async def cmd_global_enable(self, ctx: commands.Context, name: MaybeFeature) -> None:
        """Enable the specified feature globally."""
        # first validate the feature exists, then ask for confirmation
        feature = self.features.get(name)
        if not feature:
            raise commands.UserInputError("That feature does not exist.")
        if feature.enabled is True:
            raise commands.UserInputError("That feature is already enabled.")
        confirm, inter, components = await self.wait_for_confirmation(
            ctx.message, f"Are you sure you want to **enable** feature `{name}` globally?\n\u200b"
        )
        if confirm is None or inter is None:
            return
        if not confirm:
            await inter.response.edit_message("Aborted.", components=components)
            return

        logger.info(f"Attempting to enable feature {name} globally as requested by {ctx.author} ({ctx.author.id}).")
        async with self.bot.db.begin() as session:
            feature = await session.merge(feature)
            feature.enabled = True
            await session.commit()
            self.refresh_in_cache(feature)

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully **enabled** feature `{name}` globally.", components=button
        )
        logger.info(f"Successsfully enabled feature {name} globally as requested by {ctx.author} ({ctx.author.id}).")

    @cmd_global.command(name="disable")
    async def cmd_global_disable(self, ctx: commands.Context, name: MaybeFeature) -> None:
        """Disable the specified feature globally."""
        # first validate the feature exists, then ask for confirmation
        feature = self.features.get(name)
        if not feature:
            raise commands.UserInputError("That feature does not exist.")
        if feature.enabled is False:
            raise commands.UserInputError("That feature is already disabled.")
        confirm, inter, components = await self.wait_for_confirmation(
            ctx.message, f"Are you sure you want to **disable** feature `{name}` globally?\n\u200b"
        )
        if confirm is None or inter is None:
            return
        if not confirm:
            await inter.response.edit_message("Aborted.", components=components)
            return

        logger.info(f"Attempting to disable feature {name} globally as requested by {ctx.author} ({ctx.author.id}).")
        async with self.bot.db.begin() as session:
            feature = await session.merge(feature)
            feature.enabled = False
            await session.commit()
            self.refresh_in_cache(feature)

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully **disabled** feature `{name}` globally.", components=button
        )
        logger.info(f"Successsfully disabled feature {name} globally as requested by {ctx.author} ({ctx.author.id}).")

    @cmd_global.command(name="default")
    async def cmd_global_default(self, ctx: commands.Context, name: MaybeFeature) -> None:
        """Switch to guild overrides for the specified feature globally."""
        # first validate the feature exists, then ask for confirmation
        feature = self.features.get(name)
        if not feature:
            raise commands.UserInputError("That feature does not exist.")
        if feature.enabled is None:
            raise commands.UserInputError("That feature is already set to guild overrides.")
        confirm, inter, components = await self.wait_for_confirmation(
            ctx.message,
            f"Are you sure you want to **switch to guild overrides** for feature `{name}`?\n\u200b",
        )
        if confirm is None or inter is None:
            return
        if not confirm:
            await inter.response.edit_message("Aborted.", components=components)
            return

        logger.info(
            f"Attempting to globally set feature {name} to guild overrides "
            f"as requested by {ctx.author} ({ctx.author.id})."
        )
        async with self.bot.db.begin() as session:
            feature = await session.merge(feature)
            feature.enabled = None
            await session.commit()
            self.refresh_in_cache(feature)

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully changed feature `{name}` to guild overrides.", components=button
        )
        logger.info(
            f"Successfully changed feature {name} to guild overrides as requested by {ctx.author} ({ctx.author.id})."
        )

    async def show_features(
        self, inter: disnake.MessageInteraction, feature: Feature, *, with_guilds: bool = False
    ) -> None:
        """Show properties of the provided feature."""
        status = "Enabled" if feature.enabled else "Disabled" if feature.enabled is False else "Guild overrides"
        components: list = [
            disnake.ui.Container(disnake.ui.TextDisplay(f"-# **Global Features » {feature.name}**\n### {feature.name}"))
        ]
        components[-1].children.append(disnake.ui.TextDisplay(f"**Enabled**:\n{status}"))
        components[-1].children.append(
            disnake.ui.TextDisplay(f"**Rollout**:\n{feature.rollout.name if feature.rollout else 'None'}")
        )

        if with_guilds:
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
                components.append(disnake.ui.Separator())
                components.append(
                    disnake.ui.Container(
                        disnake.ui.TextDisplay("## Guilds\n" + "\n".join(guild_names) or "No guilds have overrides")
                    )
                )

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
                    custom_id=FEATURES_MAIN_LIST,
                ),
            )
        )
        await inter.response.edit_message(components=components)

    @commands.Cog.listener("on_button_click")
    async def feature_button_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for feature view buttons."""
        if not inter.component.custom_id or not inter.component.custom_id.startswith(FEATURE_VIEW_PREFIX):
            return
        # this `:` ensures that split won't fail
        custom_id = inter.component.custom_id.removeprefix(FEATURE_VIEW_PREFIX) + "::"
        feature_name, show_guilds, _ = custom_id.split(":", 2)
        show_guilds = bool(show_guilds)
        feature = self.features.get(feature_name)
        if not feature:
            await inter.response.send_message("That feature does not exist.", ephemeral=True)
            return
        await self.show_features(inter, feature, with_guilds=show_guilds)

    @commands.Cog.listener("on_button_click")
    async def features_main_list_listener(self, inter: disnake.MessageInteraction) -> None:
        """Listen for the main features list button."""
        if inter.component.custom_id != FEATURES_MAIN_LIST:
            return
        await self.cmd_list(inter)

    @cmd_features.command(name="list")
    async def cmd_list(self, ctx: commands.Context | disnake.MessageInteraction) -> None:
        """List all existing features."""
        features = sorted(self.features.items())
        components: list = [
            disnake.ui.Container(
                disnake.ui.TextDisplay(
                    textwrap.dedent(
                        """
            ### Global Features

            KEY:
            -# :blue_square: Feature force enabled globally
            -# :black_large_square: Feature uses guild overrides
            -# :red_square: Feature force disabled globally

            -# :green_circle: Feature force-enabled in this guild
            -# :black_circle: Feature not enabled in this guild
            -# :yellow_circle: Feature enabled here due to rollouts."""
                    )
                )
            )
        ]
        guild_feature_ids = []
        if isinstance(ctx.guild, disnake.Guild):
            guild = await self.bot.ensure_guild(ctx.guild.id)
            guild_feature_ids = guild.feature_ids
            check_guild = True
        else:
            check_guild = False

        for _, feature in features:
            if feature.enabled is True:
                button_style = disnake.ButtonStyle.primary
                guild_status = "\U0001f535"  # blue circle
            elif feature.enabled is None:
                button_style = disnake.ButtonStyle.secondary
                guild_status = "\U000026ab"  # black circle
            else:
                button_style = disnake.ButtonStyle.danger
                guild_status = "\U0001f534"  # red circle

            if check_guild:
                if feature.name in guild_feature_ids:
                    guild_status = "\U0001f7e2"  # green circle
                elif await self.bot.guild_has_feature(ctx.guild, feature.name):
                    guild_status = "\U0001f7e1"  # yellow circle
                else:
                    guild_status = "\U000026ab"  # black circle

            components[-1].children.append(
                disnake.ui.Section(
                    f"{feature.name}",
                    accessory=disnake.ui.Button(
                        emoji=guild_status,
                        style=button_style,
                        custom_id=f"{FEATURE_VIEW_PREFIX}{feature.name}:1",
                    ),
                )
            )

        components.append(
            disnake.ui.ActionRow(DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message))
        )
        if isinstance(ctx, disnake.MessageInteraction):
            await ctx.response.edit_message(components=components)
        else:
            await ctx.reply(components=components, fail_if_not_exists=False, mention_author=False)

    # guild commands

    @cmd_features.group(name="guild", invoke_without_command=True)
    async def cmd_guild(
        self,
        ctx: commands.Context,
        guild: Union[disnake.Guild, disnake.Object] = None,  # type: ignore
    ) -> None:
        """Commands for managing guild features."""
        # list the features by default
        if guild is None:
            guild: disnake.Guild = ctx.guild  # type: ignore
        name = guild.name if isinstance(guild, disnake.Guild) else "Guild ID " + str(guild.id)
        embed = disnake.Embed(
            title=f"Features for {name}", description="No features are enabled for this specific guild."
        )
        guild_db = await self.bot.ensure_guild(guild.id)
        if guild_db.feature_ids:
            guild_features = []
            for feature in guild_db.feature_ids:
                guild_features.append(feature)
            guild_features.sort()
            embed.description = "`" + "`\n`".join(guild_features) + "`"

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.send(embed=embed, components=button)
        logger.debug(f"User {ctx.author} ({ctx.author.id}) requested guild features for {name}")

    @cmd_guild.command(name="add", aliases=("a", "enable"), require_var_positional=True)
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

    @cmd_guild.command(name="remove", aliases=("r", "disable"), require_var_positional=True)
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

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Require all commands in this cog are by the bot author and are in guilds."""
        if await self.bot.is_owner(ctx.author):
            if not ctx.guild:
                raise commands.NoPrivateMessage()
            return True

        raise commands.NotOwner("You do not own this bot.")


def setup(bot: Monty) -> None:
    """Add the FeatureManagement cog to the bot."""
    bot.add_cog(FeatureManagement(bot))
