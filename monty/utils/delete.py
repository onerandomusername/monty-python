from typing import Sequence, Union

import disnake
import disnake.ext.commands

from monty import constants


VIEW_DELETE_ID = "wait_for_deletion_interaction_trash"


class DeleteView(disnake.ui.View):
    """This should only be used on responses from interactions."""

    def __init__(
        self,
        users: Union[disnake.User, int, Sequence[Union[disnake.User, int]]],
        initial_inter: disnake.Interaction = None,
        *,
        timeout: float = 500,
    ):
        if isinstance(users, Sequence):
            self.user_ids = {getattr(user, "id", user) for user in users}
        else:
            self.user_ids = {getattr(users, "id", users)}
        self.inter = initial_inter
        super().__init__(timeout=timeout)
        self.deleted = False

    @disnake.ui.button(
        custom_id=VIEW_DELETE_ID,
        style=disnake.ButtonStyle.grey,
        emoji=constants.Emojis.trashcan,
    )
    async def delete_button(self, button: disnake.Button, inter: disnake.MessageInteraction) -> None:
        """Delete a message when a button is pressed if the user is okay to delete it."""
        if inter.author.id in self.user_ids:
            if self.inter:
                await self.inter.followup.delete_message(inter.message.id)
            else:
                await inter.message.delete()
            self.deleted = True
            self.stop()
        else:
            await inter.response.send_message("This isn't for you!", ephemeral=True)

    async def on_timeout(self) -> None:
        """Disable the button on timeout."""
        self.delete_button.disabled = True


def get_view(ctx: Union[disnake.Interaction, disnake.ext.commands.Context, disnake.Message]) -> DeleteView:
    """Get a view that will work based on the content."""
    return DeleteView(users=ctx.author, timeout=300)
