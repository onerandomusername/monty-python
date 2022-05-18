import re
from typing import Optional, Union

import disnake
import disnake.ext.commands

from monty import constants
from monty.log import get_logger


DELETE_ID_V2 = "message_delete_button_v2:"

logger = get_logger(__name__)


def sub_clyde(username: Optional[str]) -> Optional[str]:
    """
    Replace "e"/"E" in any "clyde" in `username` with a Cyrillic "е"/"E" and return the new string.

    Discord disallows "clyde" anywhere in the username for webhooks. It will return a 400.
    Return None only if `username` is None.
    """

    def replace_e(match: re.Match) -> str:
        char = "е" if match[2] == "e" else "Е"
        return match[1] + char

    if username:
        return re.sub(r"(clyd)(e)", replace_e, username, flags=re.I)
    else:
        return username  # Empty string or None


def format_user(user: disnake.abc.User) -> str:
    """Return a string for `user` which has their mention and ID."""
    return f"{user.mention} (`{user.id}`)"


class DeleteButton(disnake.ui.Button):
    """A button that when pressed, has a listener that will delete the message."""

    def __init__(
        self,
        user: Union[int, disnake.User, disnake.Member],
        *,
        allow_manage_messages: bool = True,
        initial_message: Optional[Union[int, disnake.Message]] = None,
        style: disnake.ButtonStyle = disnake.ButtonStyle.grey,
    ):
        if isinstance(user, (disnake.User, disnake.Member)):
            user = user.id

        super().__init__()
        self.custom_id = DELETE_ID_V2
        permissions = disnake.Permissions()
        if allow_manage_messages:
            permissions.manage_messages = True
        self.custom_id += str(permissions.value) + ":"
        self.custom_id += str(user)

        self.custom_id += ":"
        if initial_message:
            if isinstance(initial_message, disnake.Message):
                initial_message = initial_message.id
            self.custom_id += str(initial_message)

        self.style = style
        self.emoji = constants.Emojis.trashcan


class DeleteView(disnake.ui.View):
    """This should only be used on responses from interactions."""

    def __init__(
        self,
        user: Union[int, disnake.User, disnake.Member],
        *,
        timeout: float = 1,
        allow_manage_messages: bool = True,
        initial_message: Optional[Union[int, disnake.Message]] = None,
    ):
        if isinstance(user, (disnake.User, disnake.Member)):
            user = user.id

        self.delete_button = DeleteButton(
            user=user, allow_manage_messages=allow_manage_messages, initial_message=initial_message
        )
        self.delete_button.row = 1
        super().__init__(timeout=timeout)
        children = self.children.copy()
        self.clear_items()
        self.add_item(self.delete_button)
        for child in children:
            self.add_item(child)
