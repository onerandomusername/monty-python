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


log = logging.getLogger(__name__)

# Number of seconds to wait for other users to bookmark the same message
TIMEOUT = 120
BOOKMARK_EMOJI = "📌"
CUSTOM_ID = "bookmark_add_bookmark"

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
        self.disable()

        await inter.response.edit_message(content=content, view=self)

    @disnake.ui.button(label="Cancel", custom_id="bookmark_delete_bookmark_cancel", style=disnake.ButtonStyle.green)
    async def cancel(self, button: disnake.ui.Button, inter: disnake.MessageInteraction) -> None:
        """Cancel the deletion and provide a response."""
        self.disable()
        await inter.response.edit_message(content="Cancelled", view=self)

    def disable(self) -> None:
        """Disable all attributes in this view."""
        for c in self.children:
            if hasattr(c, "disabled") and c.is_dispatchable():
                c.disabled = True


def check_user_read_perms(user: disnake.User, target_message: disnake.Message) -> bool:
    """Prevent users from bookmarking a message in a channel they don't have access to."""
    permissions = target_message.channel.permissions_for(user)
    return permissions.read_messages and permissions.read_message_history


class BookMarkView(disnake.ui.View):
    """Something something no low level button creation interface."""

    @disnake.ui.button(custom_id=CUSTOM_ID, style=disnake.ButtonStyle.blurple, emoji=BOOKMARK_EMOJI)
    async def add_bm(self, button: disnake.Button, inter: disnake.MessageInteraction) -> None:
        """Something something no low level button creation interface."""
        pass


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

    async def action_bookmark(
        self, channel: disnake.TextChannel, user: disnake.Member, target_message: disnake.Message, title: str
    ) -> Optional[Union[bool, disnake.Embed]]:
        """Sends the bookmark DM, or sends an error embed when a user bookmarks a message."""
        embed = self.build_bookmark_dm(target_message, title)
        try:
            components = disnake.ui.Button(
                custom_id=DELETE_CUSTOM_ID, label="Delete this bookmark", style=disnake.ButtonStyle.red
            )
            await user.send(embed=embed, components=components)
        except disnake.Forbidden:
            error_embed = self.build_error_embed(user)
            return error_embed
        else:
            log.info(f"{user} bookmarked {target_message.jump_url} with title '{title}'")

    @staticmethod
    async def send_embed(
        ctx: typing.Union[commands.Context, disnake.ApplicationCommandInteraction], target_message: disnake.Message
    ) -> typing.Tuple[disnake.Message, disnake.ui.View]:
        """Sends an embed, with a reaction, so users can react to bookmark the message too."""
        view = BookMarkView(timeout=TIMEOUT)
        embed = disnake.Embed(
            description=(
                f"Click the button below to be sent your very own bookmark to "
                f"[this message]({target_message.jump_url})."
            ),
            colour=Colours.soft_green,
        )

        if isinstance(ctx, commands.Context) and ctx.channel == target_message.channel:
            message = await ctx.send(
                embed=embed,
                reference=target_message.to_reference(fail_if_not_exists=False),
                allowed_mentions=disnake.AllowedMentions.none(),
                view=view,
            )
        else:
            message = await ctx.send(embed=embed, view=view)

        return message, view

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

        # Prevent users from bookmarking a message in a channel they don't have access to
        def check_perms(user: disnake.User, message: disnake.Message) -> bool:
            permissions = message.channel.permissions_for(user)
            if not permissions.read_message_history:
                log.info(f"{user} tried to bookmark a message in #{message.channel} but has no permissions.")
                return False
            return True

        if not check_perms(ctx.author, target_message):
            embed = disnake.Embed(
                title=random.choice(ERROR_REPLIES),
                color=Colours.soft_red,
                description="You don't have permission to view this channel.",
            )
            if isinstance(ctx, disnake.Interaction):
                await ctx.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
            return

        result = await self.action_bookmark(ctx.channel, ctx.author, target_message, title)
        if isinstance(result, disnake.Embed):
            if isinstance(ctx, disnake.Interaction):
                await ctx.send(embed=result, ephemeral=True)
            else:
                await ctx.reply(embed=result)
            return
        # Keep track of who has already bookmarked, so users can't spam reactions and cause loads of DMs
        bookmarked_users = set([ctx.author.id])
        reaction_message, _ = await self.send_embed(
            ctx,
            target_message,
        )
        # since ctx can be an interaction or context, reaction message could be None
        if not reaction_message:
            reaction_message = await ctx.original_message()

        def interaction_check(inter: disnake.MessageInteraction) -> bool:
            res = inter.data.custom_id == CUSTOM_ID and inter.message.id == reaction_message.id
            return res

        while True:
            try:
                inter: disnake.MessageInteraction = await self.bot.wait_for(
                    "message_interaction", timeout=TIMEOUT, check=interaction_check
                )
            except asyncio.TimeoutError:
                log.debug("Timed out waiting for a reaction")
                break
            if not check_perms(inter.user, target_message):
                embed = disnake.Embed(
                    title=random.choice(ERROR_REPLIES),
                    color=Colours.soft_red,
                    description="You don't have permission to view this channel.",
                )
                await inter.send(embed=embed, ephemeral=True)
                continue
            if inter.author.id in bookmarked_users:
                await inter.send("You've already bookmarked this message.", ephemeral=True)
                continue
            await inter.response.defer()
            await self.action_bookmark(ctx.channel, inter.author, target_message, title)
            bookmarked_users.add(inter.author.id)

        await reaction_message.edit(view=None)

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
        await self.bookmark(inter, inter.target)

    @commands.Cog.listener()
    async def on_message_interaction(self, inter: disnake.MessageInteraction) -> None:
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
