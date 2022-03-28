import asyncio
import logging
from typing import Union

import disnake
import disnake.ext.commands

from monty import constants


DELETE_ID_V2 = "message_delete_button_v2:"

logger = logging.getLogger(__name__)


class DeleteView(disnake.ui.View):
    """This should only be used on responses from interactions."""

    def __init__(
        self,
        user: Union[int, disnake.User],
        *,
        timeout: float = 1,
        allow_manage_messages: bool = True,
    ):
        if isinstance(user, (disnake.User, disnake.Member)):
            user = str(user.id)

        super().__init__(timeout=timeout)
        self.delete_button.custom_id = DELETE_ID_V2
        permissions = disnake.Permissions()
        if allow_manage_messages:
            permissions.manage_messages = True
        self.delete_button.custom_id += str(permissions.value) + ":"
        self.delete_button.custom_id += str(user)

    @disnake.ui.button(
        style=disnake.ButtonStyle.grey,
        emoji=constants.Emojis.trashcan,
    )
    async def delete_button(self, button: disnake.Button, inter: disnake.MessageInteraction) -> None:
        """Delete a message when a button is pressed if the user is okay to delete it."""
        await asyncio.sleep(3)
