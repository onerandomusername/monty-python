"""
Original Source: https://github.com/Rapptz/RoboDanny/blob/e1d5da9c87ec71b0c072798704254c4595ad4b94/cogs/admin.py # noqa: D415 E501

LICENSE:
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import io
import logging
import os
import sys
import textwrap
import traceback
import typing
import typing as t
from contextlib import redirect_stdout

# to expose to the eval command
from pprint import pprint
from types import FunctionType
from typing import TYPE_CHECKING, Optional, Tuple, Union

import arrow
import disnake
from disnake.ext import commands
from disnake.ext.commands import Context

from monty.metadata import ExtMetadata
from monty.utils.delete import DeleteView
from monty.utils.messages import wait_for_deletion


EXT_METADATA = ExtMetadata(core=True)
DISCORD_UPLOAD_LIMIT = 800000

globals_to_import = {
    "disnake": disnake,
    "typing": typing,
    "commands": commands,
    "pprint": pprint,
    "textwrap": textwrap,
    "os": os,
    "sys": sys,
    "io": io,
    "asyncio": asyncio,
    "arrow": arrow,
}
globals_to_import.update(builtins.__dict__)


def create_file_obj(
    input: str,
    encoding: str = "utf-8",
    name: str = "results",
    ext: str = "txt",
    spoiler: bool = False,
) -> disnake.File:
    """Create a discord file object, raising an exception if it is too big to upload."""
    encoded = input.encode(encoding)
    if len(encoded) > DISCORD_UPLOAD_LIMIT:
        raise Exception("file is too large to upload")
    fp = io.BytesIO(encoded)
    filename = f"{name}.{ext}"
    return disnake.File(fp=fp, filename=filename, spoiler=spoiler)


if TYPE_CHECKING:
    from disnake import Message

    from monty.bot import Bot


log = logging.getLogger(__name__)

Executor = Union[exec, eval]

MESSAGE_LIMIT = 2000


class Admin(commands.Cog):
    """Admin-only eval command and repr."""

    def __init__(self, bot: Bot):
        log.debug("loading cog Admin")
        self.bot = bot
        self._last_result = None
        self.sessions = set()

    def cleanup_code(self, content: str) -> str:
        """Automatically removes code blocks from the code."""
        if snekbox := self.bot.get_cog("Snekbox"):
            return snekbox.prepare_input(content)
        # fall back to legacy if Snekbox cog does not exist

        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            content = "\n".join(content.split("\n")[1:-1])

        # remove `foo`
        content = content.strip("` \n").strip("`")

        # so we can copy paste code, dedent it.
        content = textwrap.dedent(content)

        return content

    async def cog_check(self, ctx: Context) -> bool:
        """Cog-wide check if the user can run these commands."""
        return await self.bot.is_owner(ctx.author)

    def get_syntax_error(self, e: SyntaxError) -> str:
        """If there's a syntax error in the exception, get some text from it."""
        if e.text is None:
            return f"```py\n{e.__class__.__name__}: {e}\n```"
        return f'```py\n{e.text}{"^":>{e.offset}}\n{e.__class__.__name__}: {e}```'

    @staticmethod
    def _runwith(code: str) -> Executor:
        """Determine which method to run the code."""
        code = code.strip()
        if ";" in code:
            return exec
        if "\n" in code:
            return exec
        parsed_code = ast.parse(code)
        for node in ast.iter_fields(parsed_code):
            if isinstance(node, ast.Assign):
                return exec
        return eval

    async def _send_stdout(
        self,
        ctx: commands.Context,
        resp: str = None,
        error: Exception = None,
    ) -> None:
        """Send a nicely formatted eval response."""
        if resp is None and error is None:
            view = DeleteView(ctx.author)
            self.bot.loop.create_task(
                wait_for_deletion(
                    await ctx.send(
                        "No output.",
                        allowed_mentions=disnake.AllowedMentions(replied_user=False),
                        reference=ctx.message.to_reference(fail_if_not_exists=False),
                        view=view,
                    ),
                    view=view,
                )
            )
            return
        resp_file: disnake.File = None
        # for now, we're not gonna handle exceptions as files
        # unless, for some reason, it has a ``` in it
        error_file: disnake.File = None
        total_len = 0
        fmt_resp: str = "```py\n{0}```"
        fmt_err: str = "\nAn error occured. Unfortunate.```py\n{0}```"
        out = ""
        files = []

        # make a resp object
        if resp is not None:
            total_len += len(fmt_resp)
            total_len += len(resp)
            if "```" in resp:
                resp_file = True

        if error is not None:
            total_len += len(fmt_err)
            total_len += len(error)
            if "```" in error:
                error_file = True

        if total_len > MESSAGE_LIMIT or resp_file:
            log.debug("rats we gotta upload as a file")

            resp_file: disnake.File = create_file_obj(resp, ext="py")
        else:
            # good job, not a file
            log.debug("sending response as plaintext")
            out += fmt_resp.format(resp) if resp is not None else ""
        out += fmt_err.format(error) if error is not None else ""

        for f in resp_file, error_file:
            if f is not None:
                files.append(f)
        view = DeleteView(ctx.author)
        self.bot.loop.create_task(
            wait_for_deletion(
                await ctx.send(
                    out,
                    files=files,
                    allowed_mentions=disnake.AllowedMentions(replied_user=False),
                    reference=ctx.message.to_reference(fail_if_not_exists=False),
                    view=view,
                ),
                view=view,
            )
        )

    @commands.command(pass_context=True, hidden=True, name="ieval", aliases=["int_eval"])
    async def _eval(
        self, ctx: Union[commands.Context, disnake.CommandInter], *, code: str, original_ctx: commands.Context = None
    ) -> None:
        """Evaluates provided code. Owner only."""
        log.trace("command _eval executed.")
        env = {
            "bot": self.bot,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "pprint": pprint,
            "_": self._last_result,
        }

        if isinstance(ctx, disnake.Interaction):
            env["inter"] = ctx
            env["ctx"] = original_ctx
        else:
            env["ctx"] = ctx

        env.update(globals_to_import)
        code = self.cleanup_code(code)
        log.trace(f"body: {code}")
        stdout = io.StringIO()
        result = None
        error = None
        try:
            with redirect_stdout(stdout):
                runwith = self._runwith(code)
                log.trace(runwith.__name__)
                co_code = compile(
                    code,
                    "<int eval>",
                    runwith.__name__,
                    flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                )

                if inspect.CO_COROUTINE & co_code.co_flags == inspect.CO_COROUTINE:
                    awaitable = FunctionType(co_code, env)
                    result = await awaitable()
                else:
                    result = runwith(co_code, env)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            error = traceback.format_exception(exc_type, exc_value, exc_traceback)
            error.pop(1)
            error = "".join(error).strip()
        try:
            await (original_ctx or ctx).message.add_reaction("\u2705")
        except disnake.HTTPException:
            pass
        log.trace(f"result: {result}")
        if result is not None:
            pprint(result, stream=stdout)
        result = stdout.getvalue()
        if result.rstrip("\n") == "":
            result = None
        self._last_result = result
        await self._send_stdout(ctx=original_ctx or ctx, resp=result, error=error)

    @commands.command(name="inter-eval")
    async def interaction_eval(self, ctx: commands.Context, *, code: str) -> None:
        """Sends a message with a button to evaluate code."""
        button = disnake.ui.Button(
            label="Evaluate", style=disnake.ButtonStyle.green, custom_id="internal_interaction_eval"
        )
        msg = await ctx.send(
            "Press the below button to evaluate this code in an interaction context.", components=button
        )
        try:
            inter = await self.bot.wait_for(
                "message_interaction",
                check=lambda inter: inter.author == ctx.author
                and inter.component.custom_id == "internal_interaction_eval",
                timeout=20,
            )
        except asyncio.TimeoutError:
            button.disabled = True
            await msg.edit(components=button)
            return

        try:
            await self._eval(inter, code=code, original_ctx=ctx)
        finally:
            await msg.edit(content=":ok_hand:", view=None)

    @commands.command(pass_context=True, hidden=True)
    async def repl(self, ctx: Context) -> None:
        """Launches an interactive REPL session."""
        variables = {
            "ctx": ctx,
            "bot": self.bot,
            "message": ctx.message,
            "guild": ctx.guild,
            "channel": ctx.channel,
            "author": ctx.author,
            "_": None,
        }

        if ctx.channel.id in self.sessions:
            await ctx.send("Already running a REPL session in this channel. Exit it with `quit`.")
            return

        self.sessions.add(ctx.channel.id)
        await ctx.send("Enter code to execute or evaluate. `exit()` or `quit` to exit.")

        def check(m: Message) -> bool:
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.startswith("`")

        return await self._repl(ctx, variables, check)

    async def _clean_code(self, ctx: commands.Context, cleaned: str) -> Tuple[Executor, Optional[str], bool]:
        executor = exec

        stop = False
        if cleaned.count("\n") == 0:
            # single statement, potentially 'eval'
            try:
                code = compile(cleaned, "<repl session>", "eval")
            except SyntaxError:
                pass
            else:
                executor = eval
        if executor is exec:
            try:
                code = compile(cleaned, "<repl session>", "exec")
            except SyntaxError as e:
                await ctx.send(self.get_syntax_error(e))
                stop = True
        return executor, code, stop

    async def _repl(self, ctx: Context, variables: dict, check: t.Any) -> None:
        while True:
            try:
                response = await self.bot.wait_for("message", check=check, timeout=10.0 * 60.0)
            except asyncio.TimeoutError:
                await ctx.send("Exiting REPL session.")
                self.sessions.remove(ctx.channel.id)
                break
            cleaned = self.cleanup_code(response.content)
            if cleaned in ("quit", "exit", "exit()"):
                await ctx.send("Exiting.")
                self.sessions.remove(ctx.channel.id)
                return

            executor, code, stop = await self._clean_code(ctx, cleaned)

            variables["message"] = response
            fmt = None
            stdout = io.StringIO()
            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception:
                value = stdout.getvalue()
                fmt = f"```py\n{value}{traceback.format_exc()}\n```"
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = f"```py\n{value}{result}\n```"
                    variables["_"] = result
                elif value:
                    fmt = f"```py\n{value}\n```"
            try:
                if fmt is not None:
                    if len(fmt) > MESSAGE_LIMIT:
                        await ctx.send("Content too big to be printed.")
                    else:
                        await ctx.send(fmt)
            except disnake.Forbidden:
                pass
            except disnake.HTTPException as e:
                await ctx.send(f"Unexpected error: `{e}`")

    @commands.Cog.listener()
    async def on_socket_event_type(self, event_type: str) -> None:
        """Log events."""
        self.bot.socket_events[event_type] += 1

    @commands.command(aliases=("gw",))
    async def gateway(self, ctx: Context) -> None:
        """Sends current stats from the gateway."""
        embed = disnake.Embed(title="Gateway Events", color=0x00FF00)

        total_events = sum(self.bot.socket_events.values())
        events_per_second = total_events / (arrow.utcnow() - self.bot.start_time).total_seconds()

        embed.description = f"Start time: {disnake.utils.format_dt(self.bot.start_time.datetime)}\n"
        embed.description += f"Events per second: `{events_per_second:.2f}`/s\n\u200b"

        for event_type, count in self.bot.socket_events.most_common(21):
            embed.add_field(name=event_type, value=f"{count:,}", inline=True)

        view = DeleteView(ctx.author)
        self.bot.loop.create_task(wait_for_deletion(await ctx.send(embed=embed, view=view), view=view))


def setup(bot: Bot) -> None:
    """Add the Admin plugin to the bot."""
    bot.add_cog(Admin(bot))
