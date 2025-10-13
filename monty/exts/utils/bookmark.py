import asyncio
import random
from typing import TYPE_CHECKING, overload

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.constants import Colours, Icons
from monty.log import get_logger
from monty.utils import responses
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    WrappedMessageConverter = disnake.Message
else:
    from monty.utils.converters import WrappedMessageConverter

MessageTopLevelComponent = (
    disnake.ui.Section
    | disnake.ui.TextDisplay
    | disnake.ui.MediaGallery
    | disnake.ui.File
    | disnake.ui.Separator
    | disnake.ui.Container
    | disnake.ui.ActionRow
)

log = get_logger(__name__)

# Number of seconds to wait for other users to bookmark the same message
TIMEOUT = 120
BOOKMARK_EMOJI = "📌"
CUSTOM_ID = "bookmark_add_bookmark_v1:"

DELETE_CUSTOM_ID = "bookmark_delete_bookmark"


class DeleteBookmarkView(disnake.ui.View):
    """View for deleting bookmarks. Sent as a response to the delete button."""

    def __init__(self, message: disnake.Message, timeout: float = 180) -> None:
        self.message = message

        super().__init__(timeout=timeout)

    @disnake.ui.button(
        label="Confirm Deletion", custom_id="bookmark_delete_bookmark_confirm", style=disnake.ButtonStyle.danger
    )
    async def confirm(self, button: disnake.ui.Button, inter: disnake.MessageInteraction) -> None:
        """Delete the bookmark on confirmation."""
        try:
            await self.message.delete()
        except disnake.errors.NotFound:
            content = "You already deleted this message, nice try!"
        else:
            content = "Successfully deleted."

        await inter.response.edit_message(content=content, view=None)

    @disnake.ui.button(label="Cancel", custom_id="bookmark_delete_bookmark_cancel", style=disnake.ButtonStyle.green)
    async def cancel(self, button: disnake.ui.Button, inter: disnake.MessageInteraction) -> None:
        """Cancel the deletion and provide a response."""
        await inter.response.edit_message(content="Cancelled", view=None)

    def disable(self) -> None:
        """Disable all attributes in this view."""
        for c in self.children:
            if hasattr(c, "disabled") and c.is_dispatchable():
                c.disabled = True  # pyright: ignore[reportAttributeAccessIssue]


class Bookmark(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
    message_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
):
    """Creates personal bookmarks by relaying a message link to the user's DMs."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @staticmethod
    def build_bookmark_dm(target_message: disnake.Message, title: str) -> disnake.Embed:
        """Build the embed to DM the bookmark requester."""
        embed = disnake.Embed(title=title, description=target_message.content, colour=Colours.soft_green)
        embed.set_author(name=target_message.author, icon_url=target_message.author.display_avatar.url)
        embed.set_thumbnail(url=Icons.bookmark)

        if attachments := target_message.attachments:
            # set the image as the first attachment if it exists
            for attachment in attachments:
                if attachment.content_type in ("image/jpeg", "image/png"):
                    embed.set_image(attachment.url)

        return embed

    @staticmethod
    def build_error_embed(user: disnake.Member | disnake.User) -> disnake.Embed:
        """Builds an error embed for when a bookmark requester has DMs disabled."""
        return disnake.Embed(
            title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
            description=f"{user.mention}, please enable your DMs to receive the bookmark.",
            colour=responses.DEFAULT_FAILURE_COLOUR,
        )

    @staticmethod
    def check_perms(user: disnake.User | disnake.Member, message: disnake.Message) -> bool:
        """Prevent users from bookmarking a message in a channel they don't have access to."""
        if isinstance(user, disnake.User):
            # we can't check permissions for users, so we forbid it
            return False
        permissions = message.channel.permissions_for(user)
        if not permissions.read_message_history:
            log.info(f"{user} tried to bookmark a message in #{message.channel} but has no permissions.")
            return False
        return True

    async def action_bookmark(
        self,
        channel: disnake.abc.Messageable,
        user: disnake.Member | disnake.User,
        target_message: disnake.Message,
        title: str,
        *,
        bypass_read_check: bool = False,
    ) -> disnake.Embed | disnake.Message:
        """Sends the bookmark DM, or sends an error embed when a user bookmarks a message."""
        if not bypass_read_check and not self.check_perms(user, target_message):
            return disnake.Embed(
                title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
                color=responses.DEFAULT_FAILURE_COLOUR,
                description="You don't have permission to view that channel.",
            )
        embed = self.build_bookmark_dm(target_message, title)
        components = [
            disnake.ui.ActionRow(
                disnake.ui.Button(url=target_message.jump_url, label="Jump to Message"),
            ),
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    custom_id=DELETE_CUSTOM_ID, label="Delete this bookmark", style=disnake.ButtonStyle.red
                )
            ),
        ]
        try:
            message = await user.send(embed=embed, components=components)
        except disnake.Forbidden:
            return self.build_error_embed(user)
        else:
            log.info(f"{user} bookmarked {target_message.jump_url} with title '{title}'")
        return message

    @staticmethod
    async def send_embed(
        ctx: commands.Context | disnake.Interaction, target_message: disnake.Message
    ) -> disnake.Message | None:
        """Sends an embed, with a button, so users can click to bookmark the message too."""
        content = f"Sent you a DM, {ctx.author.mention}"

        embed = disnake.Embed(
            description=(
                f"If you'd also like to receive a bookmark to the linked message, click the {BOOKMARK_EMOJI} below!"
            ),
            colour=Colours.soft_green,
        )
        components = [
            disnake.ui.ActionRow(
                disnake.ui.Button(
                    custom_id=f"{CUSTOM_ID}{target_message.channel.id}-{target_message.id}",
                    style=disnake.ButtonStyle.blurple,
                    emoji=BOOKMARK_EMOJI,
                ),
                disnake.ui.Button(label="Jump to Message", url=target_message.jump_url),
            ),
        ]
        kwargs = {}
        if isinstance(ctx, commands.Context):
            app_permissions = ctx.channel.permissions_for(ctx.me)  # type: ignore
            if ctx.channel == target_message.channel and app_permissions.read_message_history:
                kwargs["reference"] = target_message.to_reference(fail_if_not_exists=False)

            allowed_mentions = disnake.AllowedMentions.none()
            allowed_mentions.users = [ctx.author]  # type: ignore

            await ctx.send(
                content=content,
                allowed_mentions=allowed_mentions,
                components=DeleteButton(ctx.author, initial_message=ctx.message),
            )
            message = await ctx.send(
                embed=embed,
                allowed_mentions=disnake.AllowedMentions.none(),
                components=components,
                **kwargs,
            )
        elif (
            ctx.context.private_channel
            or not ctx.authorizing_integration_owners.guild_id
            or (ctx.authorizing_integration_owners.guild_id and not ctx.permissions.send_messages)
        ):
            message = await ctx.response.send_message("Sent you a DM with the bookmark!", ephemeral=True)
        else:
            message = await ctx.response.send_message(
                embed=embed,
                components=components,
                allowed_mentions=disnake.AllowedMentions.none(),
            )
            await ctx.followup.send(content=content, ephemeral=True)

        return message

    @overload
    async def _bookmark(
        self,
        ctx: commands.Context,
        target_message: disnake.Message | None = None,
        *,
        title: str = "Bookmark",
    ) -> None: ...

    @overload
    async def _bookmark(
        self,
        ctx: disnake.ModalInteraction | disnake.ApplicationCommandInteraction,
        target_message: disnake.Message,
        *,
        title: str = "Bookmark",
    ) -> disnake.Message | None: ...

    async def _bookmark(
        self,
        ctx: (
            commands.Context
            | disnake.ModalInteraction
            | disnake.ApplicationCommandInteraction
            | disnake.MessageCommandInteraction
        ),
        target_message: disnake.Message | None = None,
        *,
        title: str = "Bookmark",
    ) -> disnake.Message | None:
        if not target_message:
            assert isinstance(ctx, commands.Context)
            if not ctx.message.reference or not isinstance(
                referenced_message := ctx.message.reference.resolved, disnake.Message
            ):
                msg = (
                    "You must either provide a valid message to bookmark, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
                raise commands.UserInputError(msg)
            target_message = referenced_message
        if not target_message.guild and not isinstance(
            ctx, (disnake.ModalInteraction, disnake.MessageCommandInteraction)
        ):
            msg = "You may only bookmark messages that aren't in DMs."
            raise commands.NoPrivateMessage(msg)

        result = await self.action_bookmark(
            ctx.channel,
            ctx.author,
            target_message,
            title,
            bypass_read_check=isinstance(ctx, (disnake.ModalInteraction, disnake.MessageCommandInteraction)),
        )
        if isinstance(result, disnake.Embed):
            if isinstance(ctx, disnake.Interaction):
                await ctx.send(embed=result, ephemeral=True)
            else:
                app_permissions = ctx.channel.permissions_for(ctx.me)  # type: ignore
                if app_permissions.read_message_history:
                    components = DeleteButton(ctx.author, initial_message=ctx.message)
                    await ctx.reply(embed=result, fail_if_not_exists=False, components=components)
                else:
                    components = DeleteButton(ctx.author, initial_message=ctx.message)
                    await ctx.send(embed=result, components=components)
            return
        await self.send_embed(
            ctx,
            target_message,
        )

    @commands.command(name="bookmark", aliases=("bm", "pin"))
    async def bookmark_prefix(
        self,
        ctx: commands.Context,
        target_message: WrappedMessageConverter | None,
        *,
        title: str = "Bookmark",
    ) -> None:
        """Send the author a link to `target_message` via DMs."""
        await self._bookmark(ctx, target_message, title=title)

    @commands.slash_command(name="bm", description="Bookmark a message.")
    async def bookmark_slash(
        self,
        inter: disnake.ApplicationCommandInteraction,
        message: disnake.Message,
        title: str = "Bookmark",
    ) -> None:
        """
        Bookmark a message.

        Parameters
        ----------
        message: A message to bookmark. This can be a link or id.
        title: An optional title for your direct message.
        """
        await self._bookmark(inter, message, title=title)

    @commands.message_command(
        name="Bookmark",
        install_types=disnake.ApplicationInstallTypes(guild=True, user=True),
        contexts=disnake.InteractionContextTypes(guild=True, private_channel=True),
    )
    async def message_bookmark(self, inter: disnake.MessageCommandInteraction) -> None:
        """Bookmark a message with a message command."""
        components = disnake.ui.Label(
            "Title",
            description="An optional title for this bookmark. Default is 'Bookmark'.",
            component=disnake.ui.TextInput(
                style=disnake.TextInputStyle.short,
                max_length=256,
                custom_id="title",
                placeholder="Bookmark",
                required=False,
            ),
        )
        await inter.response.send_modal(title="Bookmark", custom_id=f"bookmark-{inter.id}", components=components)
        try:
            modal_inter: disnake.ModalInteraction = await self.bot.wait_for(
                "modal_submit",
                check=lambda x: x.custom_id == f"bookmark-{inter.id}",
                timeout=180,
            )
        except asyncio.TimeoutError:
            return

        await self._bookmark(
            modal_inter,
            inter.target,
            title=modal_inter.text_values["title"],
        )

    @commands.Cog.listener("on_button_click")
    # cursed.
    async def bookmark_button(self, inter: disnake.MessageInteraction | disnake.ModalInteraction) -> None:
        """Listen for bookmarked button events and respond to them."""
        custom_id: str = inter.data.custom_id
        if not custom_id.startswith(CUSTOM_ID):
            return

        custom_id = custom_id.removeprefix(CUSTOM_ID)

        # TODO: this does not check internal components, only top level ones
        def remove_button(message: disnake.Message | None) -> list[MessageTopLevelComponent]:
            if message is None:
                return []
            comp = disnake.ui.components_from_message(message)
            for child in comp:
                if (getattr(child, "custom_id", "") or "").startswith(CUSTOM_ID):
                    comp.remove(child)
                    break
            else:
                log.warning("Button was not found to be removed.")
            return comp

        channel_id, message_id = custom_id.split("-")
        channel_id, message_id = int(channel_id), int(message_id)

        if channel_id == inter.channel.id:
            channel = inter.channel
        else:
            channel = self.bot.get_channel(channel_id)
        if channel is None:
            await inter.response.send_message("I can no longer view this channel.", ephemeral=True)
            return

        app_permissions = channel.permissions_for(channel.me)  # type: ignore
        if not app_permissions.read_message_history:
            # while we could remove the button there is no reason to as we aren't making an invalid api request
            await inter.response.send_message("I am currently unable to view the message this button is for.")
            return
        try:
            message = await channel.fetch_message(message_id)  # pyright: ignore[reportAttributeAccessIssue]
        except (disnake.NotFound, disnake.Forbidden, AttributeError):
            components = remove_button(inter.message)
            await inter.response.edit_message(components=components)
            await inter.send("This message either no longer exists or I cannot reference it.", ephemeral=True)
            return
        maybe_error = await self.action_bookmark(inter.channel, inter.author, message, title="Bookmark")
        if isinstance(maybe_error, disnake.Embed):
            await inter.send(embed=maybe_error, ephemeral=True)
        else:
            components = disnake.ui.Button(url=maybe_error.jump_url, label="Jump to Direct Messages")
            await inter.send("Sent you a direct message.", ephemeral=True, components=components)

    @commands.Cog.listener("on_button_click")
    async def maybe_delete_bookmark_button(self, inter: disnake.MessageInteraction) -> None:
        """Handle bookmark delete button interactions."""
        if inter.data.custom_id != DELETE_CUSTOM_ID:
            return

        # these are only sent in dms so there is no reason to check the author
        await inter.response.defer()
        await inter.send(
            "Are you sure you want to delete this bookmark?", ephemeral=True, view=DeleteBookmarkView(inter.message)
        )


def setup(bot: Monty) -> None:
    """Load the Bookmark cog."""
    bot.add_cog(Bookmark(bot))
