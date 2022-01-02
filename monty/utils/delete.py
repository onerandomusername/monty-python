from typing import Union

import disnake
import disnake.ext.commands

from monty import constants


VIEW_DELETE_ID = "wait_for_deletion_interaction_trash"


class DeleteView(disnake.ui.View):
    """This should only be used on responses from interactions."""

    def __init__(self, user: disnake.User = disnake.utils.MISSING, *, timeout: float = None):
        if user is disnake.utils.MISSING:
            self.use_application_command = True
            self.user_id = None
        else:
            self.user_id = user.id
            self.use_application_command = False
        super().__init__(timeout=timeout)

    @disnake.ui.button(
        label="Delete", custom_id=VIEW_DELETE_ID, style=disnake.ButtonStyle.grey, emoji=constants.Emojis.trashcan
    )
    async def button(self, button: disnake.Button, inter: disnake.MessageInteraction) -> None:
        """Delete a message when a button is pressed if the user is okay to delete it."""
        if self.use_application_command and not inter.message.type == disnake.MessageType.application_command:
            return
        check_author = self.user_id or inter.message.interaction.user.id
        if check_author == inter.author.id:
            await inter.message.delete()
        else:
            await inter.response.send_message("This isn't for you!", ephemeral=True)


def get_view(
    ctx: Union[disnake.ApplicationCommandInteraction, disnake.ext.commands.Context, disnake.Message]
) -> DeleteView:
    """Get a view that will work based on the content."""
    if isinstance(ctx, disnake.ApplicationCommandInteraction):
        view = DeleteView(user=ctx.author, timeout=300)
    else:
        view = DeleteView(user=ctx.author, timeout=300)
    return view
