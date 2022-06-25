import asyncio
from typing import NoReturn, Optional, Union

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.database import Feature
from monty.utils.converters import MaybeFeature
from monty.utils.messages import DeleteButton


class FeatureManagement(commands.Cog):
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

    @commands.group(name="features", invoke_without_command=True)
    async def cmd_features(self, ctx: commands.Context) -> None:
        """Manage features."""
        await self.cmd_list(ctx)

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

        await feature.update(["enabled"], enabled=True)
        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully **enabled** feature `{name}` globally.", components=button
        )

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

        await feature.update(["enabled"], enabled=False)
        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully **disabled** feature `{name}` globally.", components=button
        )

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

        await feature.update(["enabled"], enabled=None)
        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await inter.response.edit_message(
            content=f"Successfully changed feature `{name}` to guild overrides.", components=button
        )

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

    @cmd_features.group(name="guild", invoke_without_command=True)
    async def cmd_guild(self, ctx: commands.Context) -> NoReturn:
        """Commands for managing guild features."""
        raise commands.BadArgument("You must use add or remove subcommands.")

    @cmd_guild.command(name="add", aliases=("a",))
    async def cmd_guild_add(
        self,
        ctx: commands.Context,
        guild: Optional[Union[disnake.Guild, disnake.Object]] = None,  # type: ignore
        name: MaybeFeature = None,
    ) -> None:
        """Add the feature to the provided guild, defaulting to the local guild."""
        if guild is None:
            guild: disnake.Guild = ctx.guild  # type: ignore # this cannot be None due to cog checks

        if name is None:
            raise commands.BadArgument("name is a required argument that is missing.")
        feature = self.features.get(name)

        ctx_or_inter: Union[disnake.MessageInteraction, commands.Context[Monty]] = ctx

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

        guild_db = await self.bot.ensure_guild(guild.id)
        if feature.name in guild_db.features:
            raise commands.UserInputError(f"That feature is already enabled in guild ID `{guild.id}`.")
        try:
            guild_db.features.append(feature.name)
            await guild_db.update(["features"])
        except Exception as e:
            try:
                guild_db.features.remove(feature.name)
            except Exception:
                pass
            raise e

        button = DeleteButton(ctx_or_inter.author, allow_manage_messages=False, initial_message=ctx.message)
        if isinstance(ctx_or_inter, disnake.Interaction):
            method = ctx_or_inter.edit_original_message
        else:
            method = ctx.reply
        await method(f"Added guild id `{guild.id}` to feature set `{feature.name}`.", components=button)

    @cmd_guild.command(name="remove", aliases=("r",))
    async def cmd_guild_remove(
        self,
        ctx: commands.Context,
        guild: Optional[Union[disnake.Guild, disnake.Object]] = None,  # type: ignore
        name: MaybeFeature = None,
    ) -> None:
        """Add the feature to the provided guild, defaulting to the local guild."""
        if guild is None:
            guild: disnake.Guild = ctx.guild  # type: ignore # this cannot be None due to cog checks

        if name is None:
            raise commands.BadArgument("name is a required argument that is missing.")
        feature = self.features.get(name)

        if not feature:
            raise commands.BadArgument("That feature does not exist, and as such cannot be removed.")

        guild_db = await self.bot.ensure_guild(guild.id)
        if feature.name not in guild_db.features:
            raise commands.UserInputError(f"That feature is not enabled in guild ID `{guild.id}`.")

        guild_db.features.remove(feature.name)
        await guild_db.update(["features"])

        button = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.reply(f"Removed guild ID `{guild.id}` from feature set `{feature.name}`.", components=button)

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
