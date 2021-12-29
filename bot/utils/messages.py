import asyncio
import re
from functools import partial
from typing import Optional, Sequence

import disnake

from bot.bot import bot
from bot.constants import Emojis
from bot.log import get_logger


log = get_logger(__name__)
DELETE_ID = "wait_for_deletion_trash"


def _check(user: disnake.abc.User, *, message_id: int, allowed_users: Sequence[int], allow_mods: bool = True) -> bool:
    return user.id in allowed_users


def reaction_check(
    reaction: disnake.Reaction,
    user: disnake.abc.User,
    *,
    message_id: int,
    allowed_emoji: Sequence[str],
    allowed_users: Sequence[int],
) -> bool:
    """
    Check if a reaction's emoji and author are allowed and the message is `message_id`.

    If the user is not allowed, remove the reaction. Ignore reactions made by the bot.
    If `allow_mods` is True, allow users with moderator roles even if they're not in `allowed_users`.
    """
    right_reaction = user != bot.user and reaction.message.id == message_id and str(reaction.emoji) in allowed_emoji
    if not right_reaction:
        return False
    res = _check(user, message_id=message_id, allowed_users=allowed_users)

    if res:
        log.trace(f"Allowed reaction {reaction} by {user} on {reaction.message.id}.")
    else:
        log.trace(f"Removing reaction {reaction} by {user} on {reaction.message.id}: disallowed user.")
        bot.loop.create_task(
            reaction.message.remove_reaction(reaction.emoji, user),
            suppressed_exceptions=(disnake.HTTPException,),
            name=f"remove_reaction-{reaction}-{reaction.message.id}-{user}",
        )
    return res


def interaction_check(
    inter: disnake.MessageInteraction,
    *,
    message_id: int,
    allowed_component_ids: Sequence[str],
    allowed_users: Sequence[int],
) -> bool:
    """Check an interaction, see reaction_check for more info."""
    if inter.type != disnake.InteractionType.component:
        return False
    if inter.data.custom_id not in allowed_component_ids and inter.message.id != message_id:
        return False
    res = _check(inter.user, message_id=message_id, allowed_users=allowed_users)
    return res


async def wait_for_deletion(
    message: disnake.Message,
    user_ids: Sequence[int],
    timeout: float = 60 * 5,
) -> None:
    """
    Wait for any of `user_ids` to react with one of the `deletion_emojis` within `timeout` seconds to delete `message`.

    If `timeout` expires then the button is edited to indicate the option to delete has expired.
    """
    if message.guild is None:
        raise ValueError("Message must be sent on a guild")
    view = disnake.ui.View(timeout=timeout)
    button = disnake.ui.Button(
        label="Delete",
        emoji=Emojis.trashcan,
        style=disnake.ButtonStyle.grey,
        custom_id=DELETE_ID,
    )
    view.add_item(button)
    try:
        await message.edit(view=view)
    except disnake.NotFound:
        log.trace(f"Aborting wait_for_deletion: message {message.id} deleted prematurely.")
        return

    check = partial(
        interaction_check,
        message_id=message.id,
        allowed_component_ids=(DELETE_ID,),
        allowed_users=user_ids,
    )

    try:
        while True:
            try:
                inter: disnake.MessageInteraction = await bot.wait_for("interaction", timeout=timeout)
            except asyncio.TimeoutError:
                button.disabled = True
                await message.edit(view=view)
            else:
                # we must run the check here so we can respond to the interaction
                if not check(inter):
                    await inter.response.send_message("You do not have permissions to delete this.", ephemeral=True)
                    continue
                await message.delete()
    except disnake.NotFound:
        log.trace(f"wait_for_deletion: message {message.id} deleted prematurely.")


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
