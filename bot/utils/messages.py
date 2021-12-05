import asyncio
import logging
import re
from functools import partial
from typing import Optional, Sequence

import disnake

from bot.bot import bot
from bot.constants import Emojis


log = logging.getLogger(__name__)


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

    if user.id in allowed_users:
        log.trace(f"Allowed reaction {reaction} by {user} on {reaction.message.id}.")
        return True
    else:
        log.trace(f"Removing reaction {reaction} by {user} on {reaction.message.id}: disallowed user.")
        bot.loop.create_task(
            reaction.message.remove_reaction(reaction.emoji, user),
            suppressed_exceptions=(disnake.HTTPException,),
            name=f"remove_reaction-{reaction}-{reaction.message.id}-{user}",
        )
        return False


async def wait_for_deletion(
    message: disnake.Message,
    user_ids: Sequence[int],
    deletion_emojis: Sequence[str] = (Emojis.trashcan,),
    timeout: float = 60 * 5,
    attach_emojis: bool = True,
) -> None:
    """
    Wait for any of `user_ids` to react with one of the `deletion_emojis` within `timeout` seconds to delete `message`.

    If `timeout` expires then reactions are cleared to indicate the option to delete has expired.
    An `attach_emojis` bool may be specified to determine whether to attach the given
    `deletion_emojis` to the message in the given `context`.
    An `allow_mods` bool may also be specified to allow anyone with a role in `MODERATION_ROLES` to delete
    the message.
    """
    if message.guild is None:
        raise ValueError("Message must be sent on a guild")

    if attach_emojis:
        for emoji in deletion_emojis:
            try:
                await message.add_reaction(emoji)
            except disnake.NotFound:
                log.trace(f"Aborting wait_for_deletion: message {message.id} deleted prematurely.")
                return

    check = partial(
        reaction_check,
        message_id=message.id,
        allowed_emoji=deletion_emojis,
        allowed_users=user_ids,
    )

    try:
        try:
            await bot.wait_for("reaction_add", check=check, timeout=timeout)
        except asyncio.TimeoutError:
            try:
                await message.clear_reactions()
            except disnake.Forbidden:
                # no permissions to delete reactions
                pass
        else:
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
