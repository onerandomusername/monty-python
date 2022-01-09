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

MAX_LEN = 30_000


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
        message: disnake.Message,
        require_fenced: bool = False,
        check_is_python: bool = False,
        file_exts: set = None,
        no_len_limit: bool = False,
    ) -> tuple[bool, Optional[str], Optional[bool]]:
        """Extract code out of a message's content, attachments, or paste link within the message."""
        if file_exts is None:
            file_exts = {"py", "txt"}

        if message.attachments:
            for file in message.attachments:
                if file.filename.rsplit(".")[-1].lower() in file_exts:
                    content = await file.read()
                    try:
                        content = content.decode("utf-8")
                    except UnicodeDecodeError:
                        content = None
                    else:
                        if not no_len_limit and len(content) > MAX_LEN:
                            return False, None, None
                        else:
                            return True, content, False

        content = message.content

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

    async def _upload_to_workbin(
        self, message: disnake.Message, *, provide_link: bool = False
    ) -> tuple[bool, str, Optional[str]]:
        success, code, is_paste = await self.parse_code(
            message,
            require_fenced=False,
            check_is_python=False,
            file_exts={"py", "txt", "sql", "md", "rst", "html", "css", "js", "json"},
            no_len_limit=True,
        )
        if not success:
            return False, "This message does not have any code to extract or is too long to process.", None
        if is_paste:
            return False, "This is already a paste link.", None

        url = await send_to_paste_service(code, extension="python")
        if provide_link:
            msg = f"I've uploaded [this message]({message.jump_url}) to paste, you can view it here: <{url}>"
        else:
            msg = f"I've uploaded this message to paste, you can view it here: <{url}>"
        return True, msg, url
        ...

    @commands.message_command(name="Upload to Workbin")
    async def message_command_workbin(self, inter: disnake.MessageCommandInteraction) -> None:
        """Upload the message to the paste service."""
        success, msg, url = await self._upload_to_workbin(inter.target, provide_link=True)
        if not success:
            await inter.send(msg, ephemeral=True)
            return
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=url,
        )
        await inter.send(msg, components=button)

    @commands.command(name="paste", aliases=("p",))
    async def prefix_paste(self, ctx: commands.Context, message: disnake.Message = None) -> None:
        """Paste the contents of the provided message on workbin."""
        if not message:
            if not ctx.message.reference:
                raise commands.UserInputError(
                    "You must either provide a valid message to bookmark, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
            message = ctx.message.reference.resolved

        mentions = disnake.AllowedMentions.none()
        reference = message.to_reference(fail_if_not_exists=False)

        success, msg, url = await self._upload_to_workbin(message)

        if not success:
            await ctx.send(msg, reference=reference, allowed_mentions=mentions)
            return

        button = None
        if url:

            button = disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=url,
            )
        await ctx.send(msg, components=button, reference=reference, allowed_mentions=mentions)

    @commands.slash_command(name="paste", description="Paste a message to the workbin.")
    async def slash_paste(
        self,
        inter: disnake.ApplicationCommandInteraction,
        message: str,
    ) -> None:
        """
        Paste a messages contents to workbin..

        Parameters
        ----------
        message: A message to paste. This can be a link or id.
        """
        inter.channel_id = inter.channel.id
        try:
            message = await commands.MessageConverter().convert(inter, message)
        except (commands.MessageNotFound, commands.ChannelNotFound, commands.ChannelNotReadable):
            await inter.send("That message is not valid, or I do not have permissions to read it.", ephemeral=True)
            return

        success, msg, url = await self._upload_to_workbin(message, provide_link=True)
        if not success:
            await inter.send(msg, ephemeral=True)
            return
        button = disnake.ui.Button(
            style=disnake.ButtonStyle.url,
            label="Click to open in workbin",
            url=url,
        )
        await inter.send(msg, components=button)

    async def _format_black(
        self,
        message: disnake.Message,
        include_message: bool = False,
    ) -> tuple[bool, str, Optional[str]]:
        # success, string, link

        success, code, _ = await self.parse_code(
            message,
            require_fenced=False,
            check_is_python=False,
        )
        if not success:
            return False, "This message does not have any code to extract.", None

        json = {
            "source": code,
            "options": {"line_length": 110},
        }
        async with self.bot.http_session.post(self.black_endpoint, json=json, timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                logger.error("Black endpoint returned not a 200")
                return False, "Something went wrong internally when formatting the code. Please report this.", None

            json: dict = await resp.json()
        formatted: str = json["formatted_code"].strip()
        if include_message:
            maybe_ref_link = f"[this message]({message.jump_url}) "
        else:
            maybe_ref_link = ""

        if json["source_code"].strip() == formatted:
            logger.debug("code was formatted with black but no changes were made.")
            return True, "Formatted " + maybe_ref_link + "with black but no changes were made! \U0001f44c", None

        paste = await self.get_snekbox().upload_output(formatted, "python")
        if not paste:
            return False, "Sorry, something went wrong!", None

        msg = f"Formatted {maybe_ref_link}with black. Click the button below to view on the pastebin."
        if formatted.startswith("Cannot parse:"):
            msg = f"Attempted to format {maybe_ref_link}with black, but an error occured. Click to view."
        return True, msg, paste

    @commands.message_command(name="Format with Black")
    async def message_command_black(self, inter: disnake.MessageCommandInteraction) -> None:
        """Format the provided message with black."""
        success, msg, url = await self._format_black(inter.target, include_message=True)
        if not success:
            await inter.send(msg, ephemeral=True)
            return
        button = disnake.utils.MISSING
        if url:

            button = disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=url,
            )
        await inter.send(msg, components=button)

    @commands.command(name="blackify", aliases=("black", "bl"))
    async def prefix_black(self, ctx: commands.Context, message: disnake.Message = None) -> None:
        """Format the provided message with black."""
        if not message:
            if not ctx.message.reference:
                raise commands.UserInputError(
                    "You must either provide a valid message to bookmark, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
            message = ctx.message.reference.resolved

        mentions = disnake.AllowedMentions.none()
        reference = message.to_reference(fail_if_not_exists=False)

        success, msg, url = await self._format_black(message)

        if not success:
            await ctx.send(msg, reference=reference, allowed_mentions=mentions)
            return

        button = None
        if url:

            button = disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=url,
            )
        await ctx.send(msg, components=button, reference=reference, allowed_mentions=mentions)

    @commands.message_command(name="Run in Snekbox")
    async def run_in_snekbox(self, inter: disnake.MessageCommandInteraction) -> None:
        """Run the specified message in snekbox."""
        success, code, _ = await self.parse_code(
            inter.target,
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
