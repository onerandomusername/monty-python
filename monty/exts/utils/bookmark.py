import asyncio
import logging
import random
import typing
from typing import Optional, Union

import disnake
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import ERROR_REPLIES, Colours, Icons
from monty.utils.converters import WrappedMessageConverter
from monty.utils.messages import DeleteView


log = logging.getLogger(__name__)

# Number of seconds to wait for other users to bookmark the same message
TIMEOUT = 120
BOOKMARK_EMOJI = "📌"
CUSTOM_ID = "bookmark_add_bookmark_v1:"

DELETE_CUSTOM_ID = "bookmark_delete_bookmark"


class DeleteBookmarkView(disnake.ui.View):
    """View for deleting bookmarks. Sent as a response to the delete button."""

    def __init__(self, message: disnake.Message, timeout: float = 180):
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
                c.disabled = True


def check_user_read_perms(user: disnake.User, target_message: disnake.Message) -> bool:
    """Prevent users from bookmarking a message in a channel they don't have access to."""
    permissions = target_message.channel.permissions_for(user)
    return permissions.read_messages and permissions.read_message_history


class Bookmark(commands.Cog):
    """Creates personal bookmarks by relaying a message link to the user's DMs."""

    def __init__(self, bot: Bot):
        self.bot = bot

    @staticmethod
    def build_bookmark_dm(target_message: disnake.Message, title: str) -> disnake.Embed:
        """Build the embed to DM the bookmark requester."""
        embed = disnake.Embed(title=title, description=target_message.content, colour=Colours.soft_green)
        embed.add_field(name="Wanna give it a visit?", value=f"[Visit original message]({target_message.jump_url})")
        embed.set_author(name=target_message.author, icon_url=target_message.author.display_avatar.url)
        embed.set_thumbnail(url=Icons.bookmark)

        return embed

    @staticmethod
    def build_error_embed(user: disnake.Member) -> disnake.Embed:
        """Builds an error embed for when a bookmark requester has DMs disabled."""
        return disnake.Embed(
            title=random.choice(ERROR_REPLIES),
            description=f"{user.mention}, please enable your DMs to receive the bookmark.",
            colour=Colours.soft_red,
        )

    @staticmethod
    def check_perms(user: disnake.User, message: disnake.Message) -> bool:
        """Prevent users from bookmarking a message in a channel they don't have access to."""
        permissions = message.channel.permissions_for(user)
        if not permissions.read_message_history:
            log.info(f"{user} tried to bookmark a message in #{message.channel} but has no permissions.")
            return False
        return True

    async def action_bookmark(
        self, channel: disnake.TextChannel, user: disnake.Member, target_message: disnake.Message, title: str
    ) -> Union[disnake.Embed, disnake.Message]:
        """Sends the bookmark DM, or sends an error embed when a user bookmarks a message."""
        if not self.check_perms(user, target_message):
            return disnake.Embed(
                title=random.choice(ERROR_REPLIES),
                color=Colours.soft_red,
                description="You don't have permission to view that channel.",
            )
        embed = self.build_bookmark_dm(target_message, title)
        try:
            components = disnake.ui.Button(
                custom_id=DELETE_CUSTOM_ID, label="Delete this bookmark", style=disnake.ButtonStyle.red
            )
            message = await user.send(embed=embed, components=components)
        except disnake.Forbidden:
            error_embed = self.build_error_embed(user)
            return error_embed
        else:
            log.info(f"{user} bookmarked {target_message.jump_url} with title '{title}'")
        return message

    @staticmethod
    async def send_embed(
        ctx: typing.Union[commands.Context, disnake.Interaction], target_message: disnake.Message
    ) -> disnake.Message:
        """Sends an embed, with a button, so users can click to bookmark the message too."""
        embed = disnake.Embed(
            description=(
                f"Click the button below to be sent your very own bookmark to "
                f"[this message]({target_message.jump_url})."
            ),
            colour=Colours.soft_green,
        )
        components = disnake.ui.Button(
            custom_id=f"{CUSTOM_ID}{target_message.channel.id}-{target_message.id}",
            style=disnake.ButtonStyle.blurple,
            emoji=BOOKMARK_EMOJI,
        )
        if isinstance(ctx, commands.Context) and ctx.channel == target_message.channel:
            if ctx.channel.permissions_for(ctx.me).read_message_history:
                reference = target_message.to_reference(fail_if_not_exists=False)
            else:
                reference = None
            message = await ctx.send(
                embed=embed, allowed_mentions=disnake.AllowedMentions.none(), components=components, reference=reference
            )
        else:
            message = await ctx.send(embed=embed, components=components)

        return message

    @commands.command(name="bookmark", aliases=("bm", "pin"))
    async def bookmark(
        self,
        ctx: typing.Union[commands.Context, disnake.Interaction],
        target_message: Optional[WrappedMessageConverter],
        *,
        title: str = "Bookmark",
    ) -> None:
        """Send the author a link to `target_message` via DMs."""
        if not target_message:
            if not ctx.message.reference:
                raise commands.UserInputError(
                    "You must either provide a valid message to bookmark, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
            target_message = ctx.message.reference.resolved
        if not target_message.guild:
            raise commands.NoPrivateMessage("You may only bookmark messages that aren't in DMs.")

        result = await self.action_bookmark(ctx.channel, ctx.author, target_message, title)
        if isinstance(result, disnake.Embed):
            if isinstance(ctx, disnake.Interaction):
                await ctx.send(embed=result, ephemeral=True)
            elif ctx.channel.permissions_for(ctx.me).read_message_history:
                view = DeleteView(ctx.author, initial_message=ctx.message)
                await ctx.reply(embed=result, fail_if_not_exists=False, view=view)
            else:
                view = DeleteView(ctx.author, initial_message=ctx.message)
                await ctx.send(embed=result, view=view)
            return
        await self.send_embed(
            ctx,
            target_message,
        )

    @commands.slash_command(name="bm", description="Bookmark a message.")
    async def bookmark_slash(
        self,
        inter: disnake.ApplicationCommandInteraction,
        message: str,
        title: str = "Bookmark",
    ) -> None:
        """
        Bookmark a message.

        Parameters
        ----------
        message: A message to bookmark. This can be a link or id.
        title: An optional title for your direct message.
        """
        inter.channel_id = inter.channel.id
        try:
            message = await commands.MessageConverter().convert(inter, message)
        except (commands.MessageNotFound, commands.ChannelNotFound, commands.ChannelNotReadable):
            await inter.send("That message is not valid, or I do not have permissions to read it.", ephemeral=True)
            return
        await self.bookmark(inter, message, title=title)

    @commands.message_command(name="Bookmark")
    async def message_bookmark(self, inter: disnake.MessageCommandInteraction) -> None:
        """Bookmark a message with a message command."""
        components = disnake.ui.TextInput(
            style=disnake.TextInputStyle.short,
            max_length=256,
            label="Title",
            custom_id="title",
            required=False,
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

        await self.bookmark(modal_inter, inter.target, title=modal_inter.text_values["title"])

    @commands.Cog.listener("on_button_click")
    async def bookmark_button(self, inter: disnake.MessageInteraction) -> None:
        """Listen for bookmarked button events and respond to them."""
        if not inter.component.custom_id.startswith(CUSTOM_ID):
            return
        custom_id = inter.component.custom_id.removeprefix(CUSTOM_ID)

        def remove_button(message: disnake.Message) -> disnake.ui.View:
            view = disnake.ui.View.from_message(message)
            for child in view.children:
                if (getattr(child, "custom_id", "") or "").startswith(CUSTOM_ID):
                    view.remove_item(child)
                    break
            else:
                log.warning("Button was not found to be removed.")
            return view

        channel_id, message_id = custom_id.split("-")
        channel_id, message_id = int(channel_id), int(message_id)

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await inter.response.send("I can no longer view this channel.", ephemeral=True)
            return

        if not channel.permissions_for(channel.guild.me).read_message_history:
            # while we could remove the button there is no reason to as we aren't making an invalid api request
            await inter.response.send_message("I am currently unable to view the channel this message is from.")
            return
        try:
            message = await channel.fetch_message(message_id)
        except (disnake.NotFound, disnake.Forbidden):
            view = remove_button(inter.message)
            await inter.response.edit_message(view=view)
            await inter.send("This message either no longer exists or I cannot reference it.", ephemeral=True)
            return
        maybe_error = await self.action_bookmark(inter.channel, inter.author, message, title="Bookmark")
        if isinstance(maybe_error, disnake.Embed):
            await inter.send(embed=maybe_error, ephemeral=True)
        else:
            await inter.send(f"Sent you a [direct message](<{maybe_error.jump_url}>).", ephemeral=True)

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


def setup(bot: Bot) -> None:
    """Load the Bookmark cog."""
    bot.add_cog(Bookmark(bot))
