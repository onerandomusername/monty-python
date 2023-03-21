import asyncio
import re
from typing import Optional, Union

import disnake
import disnake.ext.commands

from monty import constants
from monty.bot import Monty
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


async def suppress_embeds(
    bot: Monty,
    message: disnake.Message,
    *,
    wait: Optional[float] = 3,
    force_wait: bool = False,
) -> bool:
    """Suppress the embeds on the provided message, after waiting for an edit to add embeds if none exist."""
    if not message.embeds or force_wait:
        if wait is not None:
            try:
                _, message = await bot.wait_for("message_edit", check=lambda b, m: m.id == message.id, timeout=wait)
            except asyncio.TimeoutError:
                pass
            if not message.embeds:
                return False
            await asyncio.sleep(0.2)
    try:
        await message.edit(suppress_embeds=True)
    except disnake.NotFound:
        # Don't send snippets if the original message was deleted.
        return False
    except disnake.Forbidden as e:
        # we're missing permissions to edit the message to remove the embed
        # its fine, since this bot is public and shouldn't require that.
        logger.warning("suppress_embeds should be called after checking for manage message permissions", exc_info=e)
        return False
    return True


class DeleteButton(disnake.ui.Button):
    """A button that when pressed, has a listener that will delete the message."""

    def __init__(
        self,
        user: Union[int, disnake.User, disnake.Member],
        *,
        allow_manage_messages: bool = True,
        initial_message: Optional[Union[int, disnake.Message]] = None,
        style: Optional[disnake.ButtonStyle] = None,
        emoji: Optional[Union[disnake.Emoji, disnake.PartialEmoji, str]] = None,
    ) -> None:
        if isinstance(user, (disnake.User, disnake.Member)):
            user_id = user.id
        else:
            user_id = user

        super().__init__()
        self.custom_id = DELETE_ID_V2
        permissions = disnake.Permissions()
        if allow_manage_messages:
            permissions.manage_messages = True
        self.custom_id += str(permissions.value) + ":"
        self.custom_id += str(user_id)

        self.custom_id += ":"
        if initial_message:
            if isinstance(initial_message, disnake.Message):
                initial_message = initial_message.id
            self.custom_id += str(initial_message)

        # set style based on if the message was provided
        if style is None:
            if initial_message:
                self.style = disnake.ButtonStyle.danger
            else:
                self.style = disnake.ButtonStyle.secondary
        else:
            self.style = style

        # set emoji based on the style
        if emoji is None:
            # use the cat trashcan in disnake and nextcord
            if isinstance(user, disnake.Member) and user.guild.id in (
                constants.Guilds.disnake,
                constants.Guilds.nextcord,
            ):
                self.emoji = constants.Emojis.trashcat_special
            elif self.style == disnake.ButtonStyle.danger:
                self.emoji = constants.Emojis.trashcan_on_red
            else:
                self.emoji = constants.Emojis.trashcan
        else:
            self.emoji = emoji


class DeleteView(disnake.ui.View):
    """This should only be used on responses from interactions."""

    def __init__(
        self,
        user: Union[int, disnake.User, disnake.Member],
        *,
        timeout: float = 1,
        allow_manage_messages: bool = True,
        initial_message: Optional[Union[int, disnake.Message]] = None,
    ) -> None:
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
