import asyncio
from typing import TYPE_CHECKING, Union

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.database import Feature
from monty.database.guild import Guild
from monty.log import get_logger
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    MaybeFeature = str
    FeatureConverter = Feature
else:
    from monty.utils.converters import FeatureConverter, MaybeFeature

logger = get_logger(__name__)


class FeatureManagement(commands.Cog, name="Feature Management"):
    """Management commands for bot features."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @property
    def features(self) -> dict[str, Feature]:
        """Shortcut to the underlying bot's feature dict."""
        return self.bot.features

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
        await feature.update(["enabled"], enabled=True)
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
        await feature.update(["enabled"], enabled=False)
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
        await feature.update(["enabled"], enabled=None)
        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully changed feature `{name}` to guild overrides.", components=button
        )
        logger.info(
            f"Successfully changed feature {name} to guild overrides as requested by {ctx.author} ({ctx.author.id})."
        )

    @cmd_features.command(name="view", aliases=("show",))
    async def cmd_show(self, ctx: commands.Context, feature: FeatureConverter, with_guilds: bool = False) -> None:
        """Show properties of the provided feature."""
        embed = disnake.Embed(title=f"Feature info: {feature.name}")
        embed.add_field("Enabled", feature.enabled)
        embed.add_field("Rollout", feature.rollout.name if feature.rollout else "None")
        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)

        if with_guilds:
            guilds = await Guild.objects.filter(features__array_contains=[feature.name]).all()
            guild_names = []
            for g in guilds:
                if dis_guild := self.bot.get_guild(g.id):
                    guild_names.append(f"{dis_guild.name} ({g.id})")
                else:
                    guild_names.append(g.id)
            guild_names.sort()
            embed.add_field(name="Guilds", value="\n".join(guild_names) or "No guilds have overrides.", inline=False)

        await ctx.send(embed=embed, components=button)

    @cmd_features.command(name="list")
    async def cmd_list(self, ctx: commands.Context) -> None:
        """List all existing features."""
        features: list[tuple[str, str]] = []
        for feature in self.features.values():
            if feature.enabled is True:
                status = ":green_circle:"
            elif feature.enabled is None:
                status = ":black_circle:"
            else:
                status = ":red_circle:"

            features.append((status, feature.name))

        features.sort(key=lambda x: x[1])
        description = ""
        for tup in features:
            description += f"{tup[0]} - `{tup[1]}`\n"

        embed = disnake.Embed(title="All Features")
        embed.description = description

        # add a column for the current guild
        if ctx.guild:
            guild = await self.bot.ensure_guild(ctx.guild.id)
            if guild.features:
                guild_features = []
                for feature in guild.features:
                    guild_features.append(feature)
                guild_features.sort()
                embed.add_field(f"{ctx.guild.name}'s Features", "`" + "`\n`".join(guild_features) + "`")

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.send(embed=embed, components=button)

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
        if guild_db.features:
            guild_features = []
            for feature in guild_db.features:
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
        if len(names) == 1:
            name = names[0]
            feature = self.features.get(name)

            if not feature:
                ...
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

                feature = await Feature.objects.create(name=name)
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
                if name in guild_db.features:
                    if len(guilds) == 1:
                        raise commands.UserInputError(f"That feature is already enabled in guild ID `{guild.id}`.")
                    else:
                        continue
                more_features.append(name)
            guild_db.features.extend(more_features)
            try:
                await guild_db.update(["features"])
            except Exception as e:
                try:
                    for item in more_features:
                        guild_db.features.remove(item)
                except Exception:
                    pass
                raise e

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
        for guild in guilds:
            guild_db = await self.bot.ensure_guild(guild.id)
            guild_dbs.append(guild_db)

            remove_features = []
            for name in feature_names:
                if name not in guild_db.features:
                    if len(guilds) == 1:
                        raise commands.UserInputError(f"That feature is not enabled in guild ID `{guild.id}`.")
                    else:
                        continue
                remove_features.append(name)
            for feature in remove_features:
                guild_db.features.remove(feature)
            await guild_db.update(["features"])

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
