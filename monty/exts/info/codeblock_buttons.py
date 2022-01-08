import logging
import re
import urllib.parse
from typing import TYPE_CHECKING, Optional

import aiohttp
import disnake
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import Paste, URLs
from monty.utils.delete import DeleteView
from monty.utils.messages import wait_for_deletion
from monty.utils.services import send_to_paste_service


if TYPE_CHECKING:
    from monty.exts.eval import Snekbox
    from monty.exts.info.codeblock._cog import CodeBlockCog

logger = logging.getLogger(__name__)

TIMEOUT = 180

AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=2.4)

PASTE_REGEX = re.compile(r"(https?:\/\/)?paste\.(disnake|nextcord)\.dev\/\S+")

MAX_LEN = 20_000


class CodeButtons(commands.Cog):
    """Adds automatic buttons to codeblocks if they match commands."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.black_endpoint = URLs.black_formatter

    def get_code(self, content: str, require_fenced: bool = False, check_is_python: bool = False) -> Optional[str]:
        """Get the code from the provided content. Parses codeblocks and assures its python code."""
        if not (snekbox := self.get_snekbox()):
            logger.trace("Could not parse message as the snekbox cog is not loaded.")
            return None
        code = snekbox.prepare_input(content, require_fenced=require_fenced)
        if not code:
            logger.trace("Parsed message but either no code was found or was too short.")
            return None
        # not required, but recommended
        if check_is_python and (codeblock := self.get_codeblock_cog()) and not codeblock.is_python_code(code):
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

        async with self.bot.http_session.get(url, timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return await resp.text()

    async def parse_code(
        self,
        content: str,
        require_fenced: bool = False,
        check_is_python: bool = False,
    ) -> tuple[bool, Optional[str], Optional[bool]]:
        """Extract code out of a message or paste link within the message."""
        code = await self.check_paste_link(content)

        if code:
            is_paste = True
        else:
            is_paste = False
            code = self.get_code(content, require_fenced=require_fenced, check_is_python=check_is_python)

        # check the code is less than a specific length and it exists
        if not code or len(code) > MAX_LEN:
            return False, None, None

        return True, code, is_paste

    def get_snekbox(self) -> Optional["Snekbox"]:
        """Get the Snekbox cog. This method serves for typechecking."""
        return self.bot.get_cog("Snekbox")

    def get_codeblock_cog(self) -> Optional["CodeBlockCog"]:
        """Get the Codeblock cog. This method serves for typechecking."""
        return self.bot.get_cog("Code Block")

    @commands.message_command(name="Upload to Workbin")
    async def upload_to_workbin(self, inter: disnake.MessageCommandInteraction) -> None:
        """Upload the message to the paste service."""
        success, code, is_paste = await self.parse_code(
            inter.target.content,
            require_fenced=False,
            check_is_python=False,
        )
        if not success:
            await inter.send("This message does not have any code to extract.", ephemeral=True)
            return
        if is_paste:
            await inter.send("This is already a paste link.", ephemeral=True)
            return

        url = await send_to_paste_service(code, extension="python")
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=url,
        )
        await inter.send("I've uploaded this message to paste, you can view it here:", components=button)

    @commands.message_command(name="Format with Black")
    async def format_black(self, inter: disnake.MessageCommandInteraction) -> None:
        """Format the provided message with black."""
        success, code, _ = await self.parse_code(
            inter.target.content,
            require_fenced=False,
            check_is_python=False,
        )
        if not success:
            await inter.send("This message does not have any code to extract.", ephemeral=True)
            return

        json = {
            "source": code,
            "options": {"line_length": 110},
        }
        async with self.bot.http_session.post(self.black_endpoint, json=json, timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                logger.error("Black endpoint returned not a 200")
                await inter.send(
                    "Something went wrong internally when formatting the code. Please report this.", ephemeral=True
                )
                return
            json: dict = await resp.json()
        formatted: str = json["formatted_code"].strip()
        if json["source_code"].strip() == formatted:
            logger.debug("code was formatted with black but no changes were made.")
            await inter.send(
                "Formatted with black but no changes were made! \U0001f44c",
            )
            return
        paste = await self.get_snekbox().upload_output(formatted, "python")
        if not paste:
            await inter.send("Sorry, something went wrong!", ephemeral=True)
            return
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=paste,
        )

        msg = "Formatted with black. Click the button below to view on the pastebin."
        if formatted.startswith("Cannot parse:"):
            msg = "Attempted to format with black, but an error occured. Click to view."
        await inter.send(
            msg,
            components=button,
        )

    @commands.message_command(name="Run in Snekbox")
    async def run_in_snekbox(self, inter: disnake.MessageCommandInteraction) -> None:
        """Run the specified message in snekbox."""
        success, code, _ = await self.parse_code(
            inter.target.content,
            require_fenced=False,
            check_is_python=False,
        )
        if not success:
            await inter.send("This message does not have any code to extract.", ephemeral=True)
            return

        await inter.response.defer()
        msg, link = await self.get_snekbox().send_eval(inter.target, code, return_result=True)

        view = DeleteView(inter.author, inter)
        if link:
            button = disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=link,
            )
            view.add_item(button)

        await inter.edit_original_message(content=msg, view=view)
        await wait_for_deletion(inter, view=view)


def setup(bot: Bot) -> None:
    """Add the CodeButtons cog to the bot."""
    if not URLs.black_formatter:
        logger.warning("Not loading codeblock buttons as black_formatter is not set.")
        return
    bot.add_cog(CodeButtons(bot))
