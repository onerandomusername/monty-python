import disnake
from disnake.ext import commands
from disnake.ui import View

from monty.bot import Monty
from monty.utils.messages import DELETE_ID_V2


VIEW_DELETE_ID_V1 = "wait_for_deletion_interaction_trash"


class DeleteManager(commands.Cog):
    """Handle delete buttons being pressed."""

    def __init__(self, bot: Monty):
        self.bot = bot

    # button schema
    # prefix:PERMS:USERID
    @commands.Cog.listener("on_button_click")
    async def handle_v2_button(self, inter: disnake.MessageInteraction) -> None:
        """Delete a message if the user is authorized to delete the message."""
        if not inter.component.custom_id.startswith(DELETE_ID_V2):
            return

        custom_id = inter.component.custom_id.removeprefix(DELETE_ID_V2)

        perms, user_id, *_ = custom_id.split(":")
        perms, user_id = int(perms), int(user_id)

        # check if the user id is the allowed user OR check if the user has any of the permissions allowed
        if inter.author.id != user_id:
            permissions = disnake.Permissions(perms)
            user_permissions = inter.channel.permissions_for(inter.author)
            if not permissions.value & user_permissions.value:
                await inter.response.send_message("Sorry, this delete button is not for you!", ephemeral=True)
                return

        if inter.channel.permissions_for(inter.guild.me).read_message_history:
            await inter.message.delete()
        else:
            await inter.response.defer()
            await inter.delete_original_message()

    @commands.Cog.listener("on_button_click")
    async def handle_v1_buttons(self, inter: disnake.MessageInteraction) -> None:
        """Handle old, legacy, buggy v1 deletion buttons that still may exist."""
        if inter.component.custom_id != VIEW_DELETE_ID_V1:
            return

        view = View.from_message(inter.message)
        # get the button from the view
        for comp in view.children:
            if VIEW_DELETE_ID_V1 == getattr(comp, "custom_id", None):
                break
        else:
            raise RuntimeError("view doesn't contain the button that was clicked.")

        comp.disabled = True
        await inter.response.edit_message(view=view)
        await inter.followup.send("This button no longer works lol.")


def setup(bot: Monty) -> None:
    """Add the DeleteManager to the bot."""
    bot.add_cog(DeleteManager(bot))
