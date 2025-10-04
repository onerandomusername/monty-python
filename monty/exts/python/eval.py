import asyncio
import re
from functools import partial
from signal import Signals
from typing import Literal, Optional, Tuple, overload

import aiohttp
import disnake
import yarl
from disnake import Message
from disnake.ext import commands

from monty.bot import Monty
from monty.constants import Auth, Endpoints, Feature
from monty.errors import APIError
from monty.log import get_logger
from monty.utils.code import prepare_input
from monty.utils.extensions import invoke_help_command
from monty.utils.helpers import utcnow
from monty.utils.messages import DeleteButton
from monty.utils.services import send_to_paste_service


log = get_logger(__name__)

# copied from PyPI cog for snek management

INLINE_EVAL_REGEX = re.compile(r"\$(?P<fence>`+)(.+)(?P=fence)")

ESCAPE_REGEX = re.compile("[`\u202e\u200b]{3,}")

MAX_PASTE_LEN = 10000

SIGKILL = 9

REEVAL_EMOJI = "\U0001f501"  # :repeat:
REEVAL_TIMEOUT = 30

HEADERS: dict[str, str] = {}
if Auth.snekbox:
    HEADERS["Authorization"] = Auth.snekbox
PLACEHOLDER_CODE = """
from random import choice

print(choice(("single quotes", 'double quotes')))

""".lstrip()


class EvalModal(disnake.ui.Modal):
    """Modal for evaluation."""

    def __init__(self, snekbox: "Snekbox", *, title: str = "Eval Code") -> None:
        components = [
            disnake.ui.Label(
                "Enter the code to evaluate:",
                component=disnake.ui.TextInput(
                    style=disnake.TextInputStyle.paragraph,
                    custom_id="code",
                    placeholder=PLACEHOLDER_CODE,
                    required=True,
                    max_length=4000,
                    min_length=1,
                ),
                description="Code must be wrapped in a code block or inline code.",
            ),
        ]
        super().__init__(title=title, components=components)
        self.snekbox = snekbox
        self.custom_id = "snekbox_eval"

    async def callback(self, inter: disnake.ModalInteraction) -> None:
        """Evaluate the provided code."""
        await inter.response.defer()
        await self.snekbox.send_eval(inter, inter.text_values["code"], original_source=True)


def predicate_eval_message_edit(ctx: commands.Context, old_msg: disnake.Message, new_msg: disnake.Message) -> bool:
    """Return True if the edited message is the context message and the content was indeed modified."""
    return new_msg.id == ctx.message.id and old_msg.content != new_msg.content


def predicate_eval_emoji_reaction(ctx: commands.Context, reaction: disnake.Reaction, user: disnake.User) -> bool:
    """Return True if the reaction REEVAL_EMOJI was added by the context message author on this message."""
    return reaction.message.id == ctx.message.id and user.id == ctx.author.id and str(reaction) == REEVAL_EMOJI


class Snekbox(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
):
    """Safe evaluation of Python code using Snekbox."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.url = yarl.URL(Endpoints.snekbox)
        self.jobs = {}

    async def post_eval(self, code: str, *, args: Optional[list[str]] = None) -> dict:
        """Send a POST request to the Snekbox API to evaluate code and return the results."""
        url = self.url / "eval"
        data: dict[str, str | list[str]] = {"input": code}

        if args is not None:
            data["args"] = args
        try:
            async with self.bot.http_session.post(
                url,
                json=data,
                raise_for_status=True,
                headers=HEADERS,
                timeout=10,
            ) as resp:
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise APIError("snekbox", 0, "Snekbox backend is offline or misconfigured.") from e

    async def upload_output(self, output: str, extension: str = "text") -> Optional[str]:
        """Upload the eval output to a paste service and return a URL to it if successful."""
        log.trace("Uploading full output to paste service...")

        if len(output) > MAX_PASTE_LEN:
            log.info("Full output is too long to upload")
            return None
        return await send_to_paste_service(self.bot, output, extension=extension)

    @staticmethod
    def get_results_message(results: dict) -> Tuple[str, str]:
        """Return a user-friendly message and error corresponding to the process's return code."""
        stdout, returncode = results["stdout"], results["returncode"]
        msg = f"Your eval job has completed with return code {returncode}"
        error = ""

        if returncode is None:
            msg = "Your eval job has failed"
            error = stdout.strip()
        elif returncode == 128 + SIGKILL:
            msg = "Your eval job timed out or ran out of memory"
        elif returncode == 255:
            msg = "Your eval job has failed"
            error = "A fatal NsJail error occurred"
        else:
            # Try to append signal's name if one exists
            try:
                name = Signals(returncode - 128).name
                msg = f"{msg} ({name})"
            except ValueError:
                pass

        return msg, error

    @staticmethod
    def get_status_emoji(results: dict) -> str:
        """Return an emoji corresponding to the status code or lack of output in result."""
        if not results["stdout"].strip():  # No output
            return ":warning:"
        elif results["returncode"] == 0:  # No error
            return ":white_check_mark:"
        else:  # Exception
            return ":x:"

    async def format_output(self, output: str) -> Tuple[str, Optional[str]]:
        """
        Format the output and return a tuple of the formatted output and a URL to the full output.

        Prepend each line with a line number. Truncate if there are over 10 lines or 1000 characters
        and upload the full output to a paste service.
        """
        log.trace("Formatting output...")

        output = output.rstrip("\n")
        original_output = output  # To be uploaded to a pasting service if needed
        paste_link = None

        if "<@" in output:
            output = output.replace("<@", "<@\u200b")  # Zero-width space

        if "<!@" in output:
            output = output.replace("<!@", "<!@\u200b")  # Zero-width space

        if ESCAPE_REGEX.findall(output):
            paste_link = await self.upload_output(original_output) or "too long to upload"
            return "Code block escape attempt detected; will not output result", paste_link

        truncated = False
        lines = output.count("\n")

        if lines > 0:
            output_lines = [f"{i:03d} | {line}" for i, line in enumerate(output.split("\n"), 1)]
            output_lines = output_lines[:11]  # Limiting to only 11 lines
            output = "\n".join(output_lines)

        if lines > 10:
            truncated = True
            if len(output) >= 1000:
                output = f"{output[:1000]}\n... (truncated - too long, too many lines)"
            else:
                output = f"{output}\n... (truncated - too many lines)"
        elif len(output) >= 1000:
            truncated = True
            output = f"{output[:1000]}\n... (truncated - too long)"

        if truncated:
            paste_link = await self.upload_output(original_output) or "too long to upload"

        output = output or "[No output]"

        return output, paste_link

    @overload
    async def send_eval(
        self,
        ctx: (
            commands.Context
            | disnake.Message
            | disnake.ApplicationCommandInteraction
            | disnake.ModalInteraction
            | disnake.MessageCommandInteraction
        ),
        code: str,
        return_result: Literal[True] = True,
        original_source: bool = False,
    ) -> tuple[str, Optional[str]]:
        pass

    @overload
    async def send_eval(
        self,
        ctx: (
            commands.Context
            | disnake.Message
            | disnake.ApplicationCommandInteraction
            | disnake.ModalInteraction
            | disnake.MessageCommandInteraction
        ),
        code: str,
        return_result: bool = False,
        original_source: bool = False,
    ) -> disnake.Message:
        pass

    async def send_eval(
        self,
        ctx: (
            Message
            | commands.Context
            | disnake.ApplicationCommandInteraction
            | disnake.MessageCommandInteraction
            | disnake.ModalInteraction
        ),
        code: str,
        return_result: bool = False,
        original_source: bool = False,
    ) -> tuple[str, Optional[str]] | disnake.Message:
        """
        Evaluate code, format it, and send the output to the corresponding channel.

        Return the bot response.
        """
        if isinstance(ctx, commands.Context):
            await ctx.trigger_typing()

        results = await self.post_eval(code)
        msg, error = self.get_results_message(results)

        if error:
            output, paste_link = error, None
        else:
            output, paste_link = await self.format_output(results["stdout"])

        icon = self.get_status_emoji(results)
        msg = f"{ctx.author.mention} {icon} {msg}.\n\n```ansi\n{output}\n```"

        log.info(f"{ctx.author}'s job had a return code of {results['returncode']}")

        if original_source:
            original_source_link = await self.upload_output(code)
            msg += f"\nOriginal code link: {original_source_link}"

        if return_result:
            return msg, paste_link

        if paste_link:
            msg = f"{msg}\nFull output: {paste_link}"

        components = DeleteButton(ctx.author)
        if isinstance(ctx, (disnake.Interaction)):
            await ctx.send(msg, components=components)
            response = await ctx.original_message()
        else:
            response = await ctx.reply(msg, components=components)

        return response

    async def continue_eval(self, ctx: commands.Context, response: disnake.Message) -> Optional[str]:
        """
        Check if the eval session should continue.

        Return the new code to evaluate or None if the eval session should be terminated.
        """
        _predicate_eval_message_edit = partial(predicate_eval_message_edit, ctx)
        _predicate_emoji_reaction = partial(predicate_eval_emoji_reaction, ctx)
        added_reaction = False
        try:
            _, new_message = await self.bot.wait_for(
                "message_edit", check=_predicate_eval_message_edit, timeout=REEVAL_TIMEOUT
            )
            await ctx.message.add_reaction(REEVAL_EMOJI)
            added_reaction = True
            await self.bot.wait_for("reaction_add", check=_predicate_emoji_reaction, timeout=30)

            code = await self.get_code(new_message)
            try:
                await response.delete()
            except disnake.NotFound:
                pass

            # if we have permissions, delete the user's reaction
            app_permissions = ctx.channel.permissions_for(ctx.me)  # type: ignore
            if app_permissions.manage_messages:
                try:
                    await ctx.message.clear_reaction(REEVAL_EMOJI)
                except disnake.Forbidden:
                    # delete our own reaction
                    await ctx.message.remove_reaction(REEVAL_EMOJI, ctx.me)
            else:
                await ctx.message.remove_reaction(REEVAL_EMOJI, ctx.me)
            added_reaction = False

        except asyncio.TimeoutError:
            if added_reaction:
                try:
                    await ctx.message.remove_reaction(REEVAL_EMOJI, ctx.me)
                except disnake.NotFound:
                    pass
            return None
        except disnake.NotFound:
            return None
        else:
            return code

    async def get_code(self, message: disnake.Message) -> Optional[str]:
        """
        Return the code from `message` to be evaluated.

        If the message is an invocation of the eval command, return the first argument or None if it
        doesn't exist. Otherwise, return the full content of the message.
        """
        log.trace(f"Getting context for message {message.id}.")
        new_ctx = await self.bot.get_context(message)

        if new_ctx.command is self.eval_command:
            log.trace(f"disnake.Message {message.id} invokes eval command.")
            split = message.content.split(maxsplit=1)
            code = split[1] if len(split) > 1 else None
        else:
            log.trace(f"disnake.Message {message.id} does not invoke eval command.")
            code = message.content

        return code

    @commands.slash_command(
        name="eval",
        contexts=disnake.InteractionContextTypes(guild=True, private_channel=True),
        install_types=disnake.ApplicationInstallTypes.all(),
    )
    async def slash_eval(self, inter: disnake.ApplicationCommandInteraction, code: Optional[str] = None) -> None:
        """
        Evaluate python code.

        Parameters
        ----------
        code: Code to evaluate, leave blank to open a modal.
        """
        if not code:
            await inter.response.send_modal(EvalModal(self))
            return

        if inter.author.id in self.jobs:
            await inter.send(
                f"{inter.author.mention} You've already got a job running - please wait for it to finish!",
                ephemeral=True,
            )
            return

        log.info(f"Received code from {inter.author} for evaluation:\n{code}")

        self.jobs[inter.author.id] = utcnow()
        code = prepare_input(code)
        try:
            await self.send_eval(inter, code)
        finally:
            del self.jobs[inter.author.id]

    @commands.command(name="eval", aliases=("e",))
    @commands.guild_only()
    async def eval_command(self, ctx: commands.Context, *, code: str = None) -> None:
        """
        Run Python code and get the results.

        This command supports multiple lines of code, including code wrapped inside a formatted code
        block. Code can be re-evaluated by editing the original message within 10 seconds and
        clicking the reaction that subsequently appears.

        We've done our best to make this sandboxed, but do let us know if you manage to find an
        issue with it!
        """
        if ctx.author.id in self.jobs:
            await ctx.send(f"{ctx.author.mention} You've already got a job running - please wait for it to finish!")
            return

        if not code:  # None or empty string
            await invoke_help_command(ctx)
            return

        log.info(f"Received code from {ctx.author} for evaluation:\n{code}")

        while True:
            self.jobs[ctx.author.id] = utcnow()
            code = prepare_input(code)
            try:
                response = await self.send_eval(ctx, code, return_result=False, original_source=True)
            finally:
                del self.jobs[ctx.author.id]

            code = await self.continue_eval(ctx, response)
            if not code:
                break
            log.info(f"Re-evaluating code from message {ctx.message.id}:\n{code}")

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message) -> None:
        """Evaluate code in the message automatically."""
        if not message.guild:
            return

        if message.author.bot:
            return

        if not await self.bot.guild_has_feature(message.guild.id, Feature.INLINE_EVALULATION):
            return

        code = "\n".join([m[-1].strip() for m in INLINE_EVAL_REGEX.findall(message.content)])

        if not code:
            return
        await self.send_eval(message, code, return_result=False)

    @commands.group("snekbox", aliases=("snek",))
    @commands.is_owner()
    async def manage_snekbox(self, ctx: commands.Context) -> None:
        """Commands for managing the snekbox instance."""
        pass

    @manage_snekbox.group("packages", aliases=("pack", "packs", "p"), invoke_without_command=True)
    async def manage_snekbox_packages(self, ctx: commands.Context) -> None:
        """Manage the packages installed on snekbox."""
        await self.list_snekbox_packages(ctx)

    @manage_snekbox_packages.command(name="list", aliases=("l",))
    async def list_snekbox_packages(self, ctx: commands.Context) -> None:
        """List all packages on snekbox."""
        try:
            async with self.bot.http_session.get(self.url / "packages", headers=HEADERS, raise_for_status=True) as resp:
                json = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise APIError("snekbox", 0, "Snekbox backend is offline or misconfigured.") from e

        embed = disnake.Embed(title="Installed packages")
        embed.description = ""
        for item in sorted(json["packages"], key=lambda x: x["name"]):
            # iterable of dicts
            embed.description += f"**{item['name']}**: {item['version']}\n"
        embed.timestamp = utcnow()
        await ctx.reply(
            embed=embed,
            components=DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message),
            fail_if_not_exists=False,
        )

    @manage_snekbox_packages.command(name="add", aliases=("install", "a"))
    async def install_snekbox_packages(self, ctx: commands.Context, *packages: str) -> None:
        """Install the specified packages to snekbox."""
        json = {"packages": packages}
        async with ctx.typing():
            try:
                async with self.bot.http_session.post(
                    self.url / "packages", headers=HEADERS, json=json, raise_for_status=True
                ) as resp:
                    pass
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise APIError("snekbox", 0, "Snekbox backend is offline or misconfigured.") from e
        await ctx.reply(
            f"[{resp.status}] Installed the packages.",
            components=DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message),
            fail_if_not_exists=False,
        )

    @manage_snekbox_packages.command(name="remove", aliases=("delete", "uninstall", "r", "d", "del"))
    async def uninstall_snekbox_package(self, ctx: commands.Context, *packages: str) -> None:
        """Uninstall the provided package from snekbox."""
        resp = None
        async with ctx.typing():
            for package in packages:
                try:
                    async with self.bot.http_session.delete(
                        self.url / "packages" / package, headers=HEADERS, raise_for_status=True
                    ) as resp:
                        pass
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    raise APIError("snekbox", 0, "Request errored.") from e
        status = resp.status if resp else "N/A"
        await ctx.reply(
            f"[{status}] Deleted the package" + ("s." if len(packages) > 1 else "."),
            components=DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message),
            fail_if_not_exists=False,
        )

    @manage_snekbox_packages.command(name="view", aliases=("info", "show"))
    async def view_snekbox_package(self, ctx: commands.Context, package: str) -> None:
        """View more specific details about a single package installed on snekbox."""
        try:
            async with self.bot.http_session.get(
                self.url / "packages" / package, headers=HEADERS, raise_for_status=True
            ) as resp:
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise APIError("snekbox", 0, "Snekbox backend is offline or misconfigured.") from e
        embed = disnake.Embed(title=f"{data['version']} -- {data['name']}")
        if url := data.get("home-page"):
            embed.url = url
        embed.description = data.get("summary", "")[:600]
        await ctx.reply(
            embed=embed,
            components=DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message),
            fail_if_not_exists=False,
        )


def setup(bot: Monty) -> None:
    """Load the Snekbox cog."""
    if not Endpoints.snekbox:
        log.warning("Snekbox URL not configured, not loading Snekbox cog.")
        return
    bot.add_cog(Snekbox(bot))
