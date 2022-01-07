import asyncio
import dataclasses
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING, Optional, Union

import disnake
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import Emojis, Paste, URLs
from monty.utils.services import send_to_paste_service


if TYPE_CHECKING:
    from monty.exts.eval import Snekbox
    from monty.exts.info.codeblock._cog import CodeBlockCog

logger = logging.getLogger(__name__)

TIMEOUT = 180

PASTE_REGEX = re.compile(r"(https?:\/\/)?paste\.(disnake|nextcord)\.dev\/\S+")

MAX_LEN = 20_000


@dataclasses.dataclass
class CodeblockMessage:
    """Represents a message that was already parsed to determine the code."""

    parsed_code: str
    reactions: set[Union[disnake.PartialEmoji, str]]


class CodeButtons(commands.Cog):
    """Adds automatic buttons to codeblocks if they match commands."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.messages: dict[int, CodeblockMessage] = {}
        self.actions = {
            Emojis.upload: self.upload_to_paste,
            Emojis.black: self.format_black,
            Emojis.snekbox: self.run_in_snekbox,
        }
        self.black_endpoint = URLs.black_formatter

    def get_code(self, content: str) -> Optional[str]:
        """Get the code from the provided content. Parses codeblocks and assures its python code."""
        if not (snekbox := self.get_snekbox()):
            logger.trace("Could not parse message as the snekbox cog is not loaded.")
            return None
        code = snekbox.prepare_input(content, require_fenced=True)
        if not code or code.count("\n") < 2:
            logger.trace("Parsed message but either no code was found or was too short.")
            return None
        # not required, but recommended
        if (codeblock := self.get_codeblock_cog()) and not codeblock.is_python_code(code):
            logger.trace("Code blocks exist but they are not python code.")
            return None
        return code

    async def check_paste_link(self, content: str) -> Optional[str]:
        """Fetch code from a paste link."""
        match = PASTE_REGEX.search(content)
        if not match:
            return None
        parsed_url = urllib.parse.urlparse(match.group(), scheme="https")
        query_strings = urllib.parse.parse_qs(parsed_url.query)
        id = query_strings["id"][0]
        url = Paste.raw_paste_endpoint.format(key=id)
        print(url)
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                return None
            return await resp.text()

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message) -> None:
        """See if a message matches the pattern."""
        if not message.guild:
            return

        if not ((perms := message.channel.permissions_for(message.guild.me)).add_reactions and perms.send_messages):
            return

        no_paste = False
        code = self.get_code(message.content)

        if not code:
            # don't despair, it could be a paste link
            code = await self.check_paste_link(message.content)
            no_paste = True

        if not code:
            return

        # check the code is less than a specific length
        if len(code) > MAX_LEN:
            logger.debug("Not adding reactions since the paste is way too long")
            return

        logger.debug("Adding reactions since message passes.")
        actions = {*self.actions.keys()}
        if no_paste:
            actions.remove(Emojis.upload)

        self.messages[message.id] = CodeblockMessage(
            code,
            actions,
        )
        for react in actions:
            await message.add_reaction(react)

        await asyncio.sleep(TIMEOUT)

        try:
            cb_msg = self.messages.pop(message.id)
        except KeyError:
            return
        for reaction in cb_msg.reactions:
            await message.remove_reaction(reaction, message.guild.me)

    @commands.Cog.listener()
    async def on_message_edit(self, before: disnake.Message, after: disnake.Message) -> None:
        """Listen for edits and relay them to the on_message listener."""
        await self.on_message(after)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: disnake.Reaction, user: disnake.User) -> None:
        """Listen for reactions on codeblock messages."""
        if not reaction.message.guild:
            return

        # DO ignore bots on reaction add
        if user.bot:
            return

        if user.id == self.bot.user.id:
            return

        if not (code_block := self.messages.get(reaction.message.id)):
            return

        if str(reaction.emoji) not in code_block.reactions:
            print(reaction.emoji)
            return
        meth = self.actions[str(reaction.emoji)]
        await reaction.message.remove_reaction(reaction, reaction.message.guild.me)
        await meth(reaction.message)

    def get_snekbox(self) -> Optional["Snekbox"]:
        """Get the Snekbox cog. This method serves for typechecking."""
        return self.bot.get_cog("Snekbox")

    def get_codeblock_cog(self) -> Optional["CodeBlockCog"]:
        """Get the Codeblock cog. This method serves for typechecking."""
        return self.bot.get_cog("Code Block")

    async def format_black(self, message: disnake.Message) -> None:
        """Format the provided message with black."""
        json = {
            "source": self.messages[message.id].parsed_code,
            "options": {"line_length": 110},
        }
        await message.channel.trigger_typing()
        async with self.bot.http_session.post(self.black_endpoint, json=json) as resp:
            if resp.status != 200:
                logger.error("Black endpoint returned not a 200")
                await message.channel.send(
                    "Something went wrong internally when formatting the code. Please report this."
                )
                return
            json: dict = await resp.json()
        formatted = json["formatted_code"].strip()
        if json["source_code"].strip() == formatted:
            logger.debug("code was formatted with black but no changes were made.")
            await message.reply(
                "Formatted with black but no changes were made! :ok_hand:",
                fail_if_not_exists=False,
            )
            return
        paste = await self.get_snekbox().upload_output(formatted, "python")
        if not paste:
            await message.channel.send("Sorry, something went wrong!")
            return
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=paste,
        )
        await message.reply(
            "Formatted with black. Click the button below to view on the pastebin.",
            fail_if_not_exists=False,
            components=button,
        )

    async def upload_to_paste(self, message: disnake.Message) -> None:
        """Upload the message to the paste service."""
        await message.channel.trigger_typing()
        url = await send_to_paste_service(self.messages[message.id].parsed_code, extension="python")
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=url,
        )
        await message.reply("I've uploaded this message to paste, you can view it here:", components=button)

    async def run_in_snekbox(self, message: disnake.Message) -> None:
        """Run the specified message in snekbox."""
        code = self.messages[message.id].parsed_code

        await self.get_snekbox().send_eval(message, code)


def setup(bot: Bot) -> None:
    """Add the CodeButtons cog to the bot."""
    if not URLs.black_formatter:
        logger.warning("Not loading codeblock buttons as black_formatter is not set.")
        return
    bot.add_cog(CodeButtons(bot))
