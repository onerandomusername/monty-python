import asyncio
import re
from collections.abc import Generator
from typing import TYPE_CHECKING

import disnake
import disnake.ext.commands

from monty import constants
from monty.log import get_logger


if TYPE_CHECKING:
    from monty.bot import Monty


DELETE_ID_V2 = "message_delete_button_v2:"

# You may be wondering why there's so many regexes, and why we aren't just using a parser.
# The unfortunate truth is that Discord's *own* markdown implementation uses regex.
# Because of that sad fact, no parser will have the bugs and nuances that Discord's
# implementation does, no matter how hard we try.
# this is taken directly from the client
# modified to have the `)` removed from the last characters.
# this is actually included if it matches with a ( within the link
# also modified to include a < if it starts with one
DISCORD_CLIENT_URL_REGEX = re.compile(r"(?P<url><?https?:\/\/[^\s<]+[^<.,:;'\"\]\s]\>?)", re.IGNORECASE)
# in order to properly get a url, `<>` should be matched to the above *after* the initial match
# this isn't intuitive, but its how Discord works.
DISCORD_CLIENT_URL_WRAPPED_REGEX = re.compile(r"(?<=\<)https?:\/\/[^\s>]+(?=\>)", re.IGNORECASE)
# I have zero idea how this regex works. I took it from the client and only modified it to add named groups
DISCORD_CLIENT_NAMED_URL_REGEX = re.compile(
    r"^\[(?P<title>(?:\[[^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*)\]\(\s*(?P<url><?(?:\([^)]*\)|[^\s\\]|\\.)*?>?)(?:\s+['\"]([\s\S]*?)['\"])?\s*\)",
    re.IGNORECASE,
)

logger = get_logger(__name__)


def sub_clyde(username: str | None) -> str | None:
    """
    Replace "e"/"E" in any "clyde" in `username` with a Cyrillic "е"/"E" and return the new string.

    Discord disallows "clyde" anywhere in the username for webhooks. It will return a 400.
    Return None only if `username` is None.
    """  # noqa: RUF002

    def replace_e(match: re.Match) -> str:
        char = "\u0435" if match[2] == "e" else "\u0415"
        return match[1] + char

    if username:
        return re.sub(r"(clyd)(e)", replace_e, username, flags=re.IGNORECASE)
    else:
        return username  # Empty string or None


async def suppress_embeds(
    bot: "Monty",
    message: disnake.Message,
    *,
    wait: float | None = 6,
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


def _validate_url(match: re.Match[str], *, group: str | int = "url") -> str:
    """Given a match, ensure that it is a valid url per Discord rules."""
    # see top of file for why we check this twice, both with the regex above and this one
    link = match.group(group)
    if link.startswith("<"):
        # starting where this match was, look for the full link
        new_match = DISCORD_CLIENT_URL_WRAPPED_REGEX.match(match.string, match.pos)
        # match can be false if user provided a link with no second >, in which case the client ignores the `<`
        if new_match:
            link = match.group()
        else:
            # remove the `<` from the original link.
            # The wrapped regex only checks for their existence but does not match them
            link = link[1:]
        # this looks wrong, but this is how the Discord client parses links wrapped with `>` as of April 2023
        # the very first `>` in the url is what is used for embed suppression
        # however, links NOT wrapped in `<>` can contain `>` so this check happens here and not sooner
        link = link.split(">", 1)[0]

    # if the link is wrapped, the other rules do not apply and the link is used as is.
    # in order to know if the link includes the `)` at the end, the client checks if these are part of a group (
    elif link.endswith(")"):
        # the client only cares if the link *ever* gets equalised, with the same number of ( and ) starting from the
        # end of the link. For example, https://example.com/)() will include the final )  because it was equalised
        # with a ( at some point. On the other hand, https://example.com/()) will NOT include the final `)`  because
        # the ) were not equalised with the (
        depth = -1
        for char in link[-2::-1]:
            if char == ")":
                depth -= 1
            elif char == "(":
                depth += 1
            if depth == 0:
                break
        else:
            # not part of the link
            link = link[:-1]

    return link


def extract_urls(content: str) -> Generator[str, None, None]:
    """Extract all client rendered urls from the provided message content."""
    # match the newer [label](url) format FIRST, as its more explicit
    pos = 0
    while pos < len(content):
        for regex in (DISCORD_CLIENT_NAMED_URL_REGEX, DISCORD_CLIENT_URL_REGEX):
            match: re.Match[str] | None = regex.match(content, pos)
            if match:
                break
        else:
            pos += 1
            continue
        link = _validate_url(match, group="url")
        yield link
        pos = match.start("url") + len(link)


def extract_one_url(content: str) -> str | None:
    """Variation of extract_urls which returns a single url."""
    return next(extract_urls(content), None)


class DeleteButton(disnake.ui.Button):
    """A button that when pressed, has a listener that will delete the message."""

    def __init__(
        self,
        user: int | disnake.User | disnake.Member,
        *,
        allow_manage_messages: bool = True,
        initial_message: int | disnake.Message | None = None,
        style: disnake.ButtonStyle | None = None,
        emoji: disnake.Emoji | disnake.PartialEmoji | str | None = None,
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
        user: int | disnake.User | disnake.Member,
        *,
        timeout: float = 1,
        allow_manage_messages: bool = True,
        initial_message: int | disnake.Message | None = None,
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
