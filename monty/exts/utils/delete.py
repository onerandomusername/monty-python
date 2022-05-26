import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.log import get_logger
from monty.utils.messages import DELETE_ID_V2


VIEW_DELETE_ID_V1 = "wait_for_deletion_interaction_trash"

logger = get_logger(__name__)


class DeleteManager(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Handle delete buttons being pressed."""

    def __init__(self, bot: Monty):
        self.bot = bot

    # button schema
    # prefix:PERMS:USERID
    # optional :MSGID
    @commands.Cog.listener("on_button_click")
    async def handle_v2_button(self, inter: disnake.MessageInteraction) -> None:
        """Delete a message if the user is authorized to delete the message."""
        if not inter.component.custom_id.startswith(DELETE_ID_V2):
            return

        custom_id = inter.component.custom_id.removeprefix(DELETE_ID_V2)

        perms, user_id, *extra = custom_id.split(":")
        delete_msg = None
        if extra:
            if extra[0]:
                delete_msg = int(extra[0])

        perms, user_id = int(perms), int(user_id)

        # check if the user id is the allowed user OR check if the user has any of the permissions allowed
        if not (is_orig_author := inter.author.id == user_id):
            permissions = disnake.Permissions(perms)
            user_permissions = inter.permissions
            if not permissions.value & user_permissions.value:
                await inter.response.send_message("Sorry, this delete button is not for you!", ephemeral=True)
                return

        if (
            not hasattr(inter.channel, "guild")
            or not (myperms := inter.channel.permissions_for(inter.me)).read_messages
        ):
            await inter.response.defer()
            await inter.delete_original_message()
            return

        await inter.message.delete()
        if not delete_msg or not myperms.manage_messages or not is_orig_author:
            return
        if msg := inter.bot.get_message(delete_msg):
            if msg.edited_at:
                return
        else:
            msg = inter.channel.get_partial_message(delete_msg)
        try:
            await msg.delete()
        except disnake.NotFound:
            pass
        except disnake.Forbidden:
            logger.warning("Cache is unreliable, or something weird occured.")

    @commands.Cog.listener("on_button_click")
    async def handle_v1_buttons(self, inter: disnake.MessageInteraction) -> None:
        """Handle old, legacy, buggy v1 deletion buttons that still may exist."""
        if inter.component.custom_id != VIEW_DELETE_ID_V1:
            return

        view = disnake.ui.View.from_message(inter.message)
        # get the button from the view
        for comp in view.children:
            if VIEW_DELETE_ID_V1 == getattr(comp, "custom_id", None):
                break
        else:
            raise RuntimeError("view doesn't contain the button that was clicked.")

        comp.disabled = True
        await inter.response.edit_message(view=view)
        await inter.followup.send("This button should not have been enabled, and no longer works.", ephemeral=True)


def setup(bot: Monty) -> None:
    """Add the DeleteManager to the bot."""
    bot.add_cog(DeleteManager(bot))
