import asyncio
import re
import urllib.parse
from typing import TYPE_CHECKING, Literal, cast

import aiohttp
import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.constants import Endpoints
from monty.errors import MontyCommandError
from monty.log import get_logger
from monty.utils.code import prepare_input
from monty.utils.messages import DeleteButton, extract_urls
from monty.utils.services import send_to_paste_service


if TYPE_CHECKING:
    from monty.exts.filters.codeblock._cog import CodeBlockCog
    from monty.exts.python.eval import Snekbox

logger = get_logger(__name__)

TIMEOUT = 180

AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=2.4)

# we use `extract_urls` to match for full urls, and this regex to match the start of the url
PASTE_REGEX = re.compile(
    r"^(https?:\/\/)(?:workbin\.dev|(?:paste\.(?:(?:disnake|nextcord|vcokltfre)\.dev|vcokltf\.re)))\/.+"
)

MAX_LEN = 30_000


class CodeBlockActions(
    commands.Cog,
    name="Code Block Actions",
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
    message_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
):
    """Adds automatic buttons to codeblocks if they match commands."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.black_endpoint = Endpoints.black_formatter

    def get_code(self, content: str, require_fenced: bool = False, check_is_python: bool = False) -> str | None:
        """Get the code from the provided content. Parses codeblocks and assures its python code."""
        code = prepare_input(content, require_fenced=require_fenced)
        if not code:
            logger.trace("Parsed message but either no code was found or was too short.")
            return None
        # not required, but recommended
        if check_is_python and (codeblock := self.get_codeblock_cog()) and not codeblock.is_python_code(code):
            logger.trace("Code blocks exist but they are not python code.")
            return None
        return code

    async def check_paste_link(self, content: str) -> str | None:
        """Fetch code from a paste link."""
        match: re.Match[str] | None = next(filter(None, map(PASTE_REGEX.match, extract_urls(content))), None)
        if not match:
            return None

        parsed_url = urllib.parse.urlparse(match.group(), scheme="https")
        query_strings = urllib.parse.parse_qs(parsed_url.query)
        if not query_strings.get("id"):
            return None

        id = query_strings["id"][0]
        url = Endpoints.raw_paste.format(key=id)

        async with self.bot.http_session.get(url, timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            json = await resp.json()
        return json["content"]

    async def parse_code(
        self,
        message: disnake.Message,
        require_fenced: bool = False,
        check_is_python: bool = False,
        file_exts: set | None = None,
        no_len_limit: bool = False,
    ) -> tuple[Literal[False], None, None] | tuple[Literal[True], str, bool]:
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

    def get_snekbox(self) -> "Snekbox":
        """Get the Snekbox cog. This method serves for typechecking."""
        snekbox = cast("Snekbox | None", self.bot.get_cog("Snekbox"))
        if not snekbox:
            msg = "Snekbox cog is not available."
            raise ValueError(msg)
        return snekbox

    def get_codeblock_cog(self) -> "CodeBlockCog":
        """Get the Codeblock cog. This method serves for typechecking."""
        codeblock = cast("CodeBlockCog | None", self.bot.get_cog("Code Block"))
        if not codeblock:
            msg = "Code Block cog is not available."
            raise ValueError(msg)
        return codeblock

    async def _upload_to_workbin(
        self,
        message: disnake.Message,
    ) -> tuple[bool, str, str | None]:
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
        if not code:
            return False, "No code found.", None

        url = await send_to_paste_service(self.bot, code, extension="python")

        msg = f"I've uploaded this message to paste, you can view it here: <{url}>"
        return True, msg, url

    @commands.message_command(name="Upload to Workbin")
    async def message_command_workbin(self, inter: disnake.MessageCommandInteraction) -> None:
        """Upload the message to the paste service."""
        success, msg, url = await self._upload_to_workbin(inter.target)
        if not success:
            raise MontyCommandError(msg)

        components: list[disnake.ui.Button] = [
            DeleteButton(inter.author),
            disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=url,
            ),
            disnake.ui.Button(label="View original message", url=inter.target.jump_url),
        ]
        await inter.send(msg, components=components)

    @commands.command(name="paste", aliases=("p",))
    async def prefix_paste(self, ctx: commands.Context, message: disnake.Message | None = None) -> None:
        """Paste the contents of the provided message on workbin."""
        if not message:
            if not ctx.message.reference or not isinstance(ctx.message.reference.resolved, disnake.Message):
                msg = (
                    "You must either provide a valid message to paste, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
                raise commands.UserInputError(msg)
            message = ctx.message.reference.resolved

        mentions = disnake.AllowedMentions.none()
        reference = message.to_reference(fail_if_not_exists=False)

        success, msg, url = await self._upload_to_workbin(message)

        if not success:
            await ctx.send(msg, reference=reference, allowed_mentions=mentions)
            return

        components: list[disnake.ui.Button] = [DeleteButton(ctx.author)]
        if url and url.startswith("http"):
            components.append(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.url,
                    label="Click to open in workbin",
                    url=url,
                )
            )
        components.append(disnake.ui.Button(label="View original message", url=message.jump_url))
        await ctx.send(msg, components=components, reference=reference, allowed_mentions=mentions)

    @commands.slash_command(name="paste", description="Paste a message to the workbin.")
    async def slash_paste(
        self,
        inter: disnake.ApplicationCommandInteraction,
        message: disnake.Message,
    ) -> None:
        """
        Paste a messages contents to workbin..

        Parameters
        ----------
        message: A message to paste. This can be a link or id.
        """
        success, msg, url = await self._upload_to_workbin(message)
        if not success:
            raise MontyCommandError(msg)

        components: list[disnake.ui.Button] = [
            DeleteButton(inter.author),
            disnake.ui.Button(
                style=disnake.ButtonStyle.url,
                label="Click to open in workbin",
                url=url,
            ),
            disnake.ui.Button(url=message.jump_url, label="Jump to message"),
        ]

        await inter.send(msg, components=components)

    async def _format_black(
        self,
        message: disnake.Message,
        include_message: bool = False,
    ) -> tuple[bool, str, str | None]:
        # success, string, link
        if not self.black_endpoint:
            msg = "Black endpoint is not configured."
            raise RuntimeError(msg)

        success, code, _ = await self.parse_code(
            message,
            require_fenced=False,
            check_is_python=False,
        )
        if not success:
            return False, "This message does not have any code to extract.", None

        json = {
            "source": code,
            "options": {"line_length": 110, "fast": True},
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

        if json["source_code"].strip() == formatted.strip():
            logger.debug("code was formatted with black but no changes were made.")
            return True, "Formatted " + maybe_ref_link + "with black but no changes were made! \U0001f44c", None

        paste = await self.get_snekbox().upload_output(formatted, "python")
        if not paste:
            return False, "Sorry, something went wrong!", None

        msg = f"Formatted {maybe_ref_link}with black. Click the button below to view on the pastebin."
        if formatted.startswith(("Cannot parse:", "unindent does not match any outer indentation level")):
            msg = f"Attempted to format {maybe_ref_link}with black, but an error occured. Click to view."
        return True, msg, paste

    @commands.message_command(name="Format with Black")
    async def message_command_black(self, inter: disnake.MessageCommandInteraction) -> None:
        """Format the provided message with black."""
        success, msg, url = await self._format_black(inter.target)
        if not success:
            raise MontyCommandError(msg)

        components: list[disnake.ui.Button] = [DeleteButton(inter.author)]
        if url:
            components.append(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.url,
                    label="Click to open in workbin",
                    url=url,
                )
            )
        components.append(disnake.ui.Button(label="View original message", url=inter.target.jump_url))
        await inter.send(msg, components=components)

    @commands.command(name="blackify", aliases=("black", "bl"))
    async def prefix_black(self, ctx: commands.Context, message: disnake.Message | None = None) -> None:
        """Format the provided message with black."""
        if not message:
            if not ctx.message.reference or not isinstance(
                resolved_message := ctx.message.reference.resolved, disnake.Message
            ):
                msg = (
                    "You must either provide a valid message to format with black, or reply to one."
                    "\n\nThe lookup strategy for a message is as follows (in order):"
                    "\n1. Lookup by '{channel ID}-{message ID}' (retrieved by shift-clicking on 'Copy ID')"
                    "\n2. Lookup by message ID (the message **must** be in the context channel)"
                    "\n3. Lookup by message URL"
                )
                raise commands.UserInputError(msg)
            message = resolved_message

        mentions = disnake.AllowedMentions.none()
        reference = message.to_reference(fail_if_not_exists=False)

        success, msg, url = await self._format_black(message)

        if not success:
            await ctx.send(msg, reference=reference, allowed_mentions=mentions)
            return

        components = []
        if url:
            components.append(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.url,
                    label="Click to open in workbin",
                    url=url,
                )
            )
        await ctx.send(msg, components=components, reference=reference, allowed_mentions=mentions)

    @commands.message_command(
        name="Run in Snekbox",
        install_types=disnake.ApplicationInstallTypes.all(),
        contexts=disnake.InteractionContextTypes(guild=True, private_channel=True),
    )
    async def run_in_snekbox(self, inter: disnake.MessageCommandInteraction) -> None:
        """Run the specified message in snekbox."""
        success, code, _ = await self.parse_code(
            inter.target,
            require_fenced=False,
            check_is_python=False,
        )
        if not success or not code:
            msg = "This message does not have any code to extract."
            raise MontyCommandError(msg)

        target = inter.target
        original_source = False
        modal_inter: disnake.ModalInteraction | None = None

        # only provide a modal if the code is short enough
        if code and len(code) <= 4000:
            modal_components = disnake.ui.Label(
                text="Code",
                description="Modify the code before running it.",
                component=disnake.ui.TextInput(
                    custom_id="code",
                    style=disnake.TextInputStyle.long,
                    value=code,
                    required=True,
                ),
            )
            await inter.response.send_modal(
                title="Run in Snekbox", custom_id=f"snekbox-eval-{inter.id}", components=modal_components
            )

            try:
                modal_inter = cast(
                    "disnake.ModalInteraction",
                    await self.bot.wait_for(
                        "modal_submit",
                        timeout=300,
                        check=lambda m, inter=inter: m.custom_id == f"snekbox-eval-{inter.id}" and m.user == inter.user,
                    ),
                )
            except asyncio.TimeoutError:
                return
            new_code = modal_inter.text_values["code"]
            if code != new_code:
                code = new_code
                original_source = True

        await (modal_inter or inter).response.defer()
        msg, link = await self.get_snekbox().send_eval(
            target, code, return_result=True, original_source=original_source
        )

        components: list[disnake.ui.Button] = [DeleteButton(inter.author)]
        if link and link.startswith("http"):
            components.append(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.url,
                    label="Click to open in workbin",
                    url=link,
                )
            )

        await (modal_inter or inter).edit_original_message(content=msg, components=components)


def setup(bot: Monty) -> None:
    """Add the CodeBlockActions cog to the bot."""
    if not Endpoints.black_formatter:
        logger.warning("Not loading codeblock buttons as black_formatter is not set.")
        return
    bot.add_cog(CodeBlockActions(bot))
