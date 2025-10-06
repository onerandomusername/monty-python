"""Evaluation features for Monty. These commands provide the ability to evaluate code within the bot context."""

import ast
import asyncio
import contextlib
import enum
import io
import sys
import types
from dataclasses import dataclass, field
from typing import Any, Sequence, Union

import disnake
import rich.console
import rich.pretty
import rich.text
from disnake.ext import commands

from monty import constants
from monty.bot import Monty
from monty.metadata import ExtMetadata
from monty.utils.code import prepare_input
from monty.utils.messages import DeleteButton


EXT_METADATA = ExtMetadata(core=True)

MessageTopLevelComponent = Union[
    "disnake.ui.Section",
    "disnake.ui.TextDisplay",
    "disnake.ui.MediaGallery",
    "disnake.ui.File",
    "disnake.ui.Separator",
    "disnake.ui.Container",
    "disnake.ui.ActionRow",
]


class EvalRules(enum.IntFlag):
    sort_lists = enum.auto()
    pprint_result = enum.auto()
    dual_await = enum.auto()
    modify_return_underscore = enum.auto()


@dataclass
class Result:
    raw_value: Any = None
    errors: list[Exception] = field(default_factory=list)
    message: str | None = None
    stdout: str | None = None
    _: list[Any] = field(default_factory=list)
    local_vars: dict[str, Any] = field(default_factory=dict)

    @property
    def value(self) -> str:
        """Return a string representation of the raw_value."""
        return repr(self.raw_value)


@dataclass
class Response:
    files: list[disnake.File] = field(default_factory=list)
    components: list[MessageTopLevelComponent] = field(default_factory=list)


class InternalEval(commands.Cog):
    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self._repl_session = asyncio.Lock()

    def get_tree(self, code: str, *, modify: bool = False) -> tuple[list[ast.stmt], bool]:
        """Parse code into an AST module, and add a _ assignment to the last statement if desired."""
        # we force an ast parse to see if we can make the final statement an assignment to `_` so we can print the repr
        tree = ast.parse(code, filename="<ieval>", mode="exec")

        added_underscore = False
        if modify:
            last_node = tree.body[-1]
            if isinstance(last_node, ast.Expr):
                # If the last node is an expression, assign it to `_` to print it later
                tree.body[-1] = ast.Assign(
                    targets=[ast.Name(id="_", ctx=ast.Store())],
                    value=last_node.value,
                )
                added_underscore = True

        return tree.body, added_underscore

    async def _run_stmt(self, stmt: ast.stmt, global_vars: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        """Run a single statement. stdout won't be redirected."""
        use_await = False
        for node in ast.walk(stmt):
            if isinstance(node, ast.Await):
                use_await = True
                break
        if isinstance(stmt, ast.Expr):
            # If it's a bare expression, we want to capture its value
            stmt = ast.Assign(
                targets=[ast.Name(id="_", ctx=ast.Store())],
                value=stmt.value,
            )
        ast.fix_missing_locations(stmt)
        code = compile(ast.Module(body=[stmt], type_ignores=[]), "<string>", "exec", ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        if use_await:
            res = await types.LambdaType(code, global_vars)()  # type: ignore
        else:
            res = eval(code, global_vars)  # noqa: S307
        return res, global_vars

    async def run_code(self, code: str, global_vars: dict[str, Any], *, rules: EvalRules) -> Result:
        """Run code in an async context if necessary."""
        result = Result()
        try:
            tree, added_underscore = self.get_tree(code, modify=EvalRules.modify_return_underscore in rules)
        except SyntaxError as e:
            result.errors.append(e.with_traceback(None))
            return result

        maybe_value = None

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            for stmt in tree:
                try:
                    maybe_value, global_vars = await self._run_stmt(stmt, global_vars)
                except Exception as e:
                    result.errors.append(e)
                    break
                if "_" in global_vars and global_vars["_"] is not None:
                    result._.append(global_vars["_"])

            result.stdout = stdout.getvalue()
        result.raw_value = maybe_value
        if result._ and added_underscore:
            result.raw_value = result._.pop()

        result.local_vars.update(global_vars)

        return result

    def make_pretty(
        self,
        result: Result,
        rules: EvalRules,
        *,
        use_ansi: bool = True,
    ) -> Result:
        """Modify the result to be pretty-printed if the rules specify it."""
        if EvalRules.sort_lists in rules and isinstance(result.raw_value, (list, set, tuple)):
            try:
                result.raw_value = sorted(result.raw_value)
            except TypeError:
                # If the list contains unorderable types, we skip sorting
                pass

        if EvalRules.pprint_result in rules:
            with io.StringIO() as buf:
                console = rich.console.Console(file=buf, no_color=not use_ansi, color_system="standard")
                if result.raw_value is not None:
                    rich.pretty.pprint(result.raw_value, console=console)
                result.raw_value = buf.getvalue()
                new_results = []
                for val in result._:
                    buf.seek(0)
                    buf.truncate(0)
                    rich.pretty.pprint(val, console=console)
                    new_results.append(buf.getvalue())
                result._ = new_results
        return result

    def check_limits_to_file(self, result: Result) -> bool:
        """Check if the result exceeds any limits. Returns True if it does."""
        # Currently no limits are enforced
        return False

    def maybe_file(
        self,
        content: str,
        *,
        prefix: str = "result",
        suffix: str = "txt",
        length: int = 2000,
    ) -> tuple[str, disnake.File] | None:
        """If the content is too long, return a file instead of a string. Returns a tuple of filename and file."""
        # TODO: Files are not previewed in components v2
        # either revert to components v1 or Figure out some different long-output strategy
        if len(content) > length:
            # strip ansi
            content = rich.text.Text.from_ansi(content).plain
            filename = f"{prefix}.{suffix}"
            file = disnake.File(io.BytesIO(content.encode()), filename=filename)  # TODO: fix in Disnake
            return filename, file
        return None

    def get_component_for_segment(
        self, *, content: str, title: str, language: str, display_colour: int | disnake.Colour | None = None
    ) -> tuple[disnake.ui.Container | list[Any], disnake.File | None]:
        """Get a UI component for a given segment of text."""
        file = None
        file_tuple = self.maybe_file(content, prefix="output", suffix="txt")
        if file_tuple:
            filename, file = file_tuple
            container = disnake.ui.Container(
                disnake.ui.TextDisplay(f"Output too long, sent as file `{filename}`."),
                disnake.ui.File(f"attachment://{filename}"),
            )
        elif content.strip():
            container = disnake.ui.Container(disnake.ui.TextDisplay(f"**{title}:**\n```{language}\n{content}\n```"))
        else:
            container = disnake.ui.Container(disnake.ui.TextDisplay(f"**{title}:**\n*No output.*"))

        if display_colour is None:
            display_colour = constants.Colours.python_yellow
        if isinstance(display_colour, int):
            display_colour = disnake.Colour(display_colour)
        container.accent_color = display_colour
        return container.children, file

    def add_segments(
        self,
        response: Response,
        *,
        components: Sequence[MessageTopLevelComponent] | disnake.ui.Container | None = None,
        files: Sequence[disnake.File] | disnake.File | None = None,
    ) -> None:
        """Add components to a response, ensuring they are in action rows."""
        if components:
            if isinstance(components, Sequence):
                response.components.extend(components)
            else:
                response.components.append(components)
        if files:
            if isinstance(files, Sequence):
                response.files.extend(files)
            else:
                response.files.append(files)

    def get_formatted_response(self, result: Result) -> Response:
        """Formulate a response message based on the result."""
        response = Response()
        components: list[disnake.ui.Container] = []
        if result.raw_value is not None and result.raw_value.strip():
            component, file = self.get_component_for_segment(
                content=result.raw_value, title="Result", language="ansi", display_colour=disnake.Colour.greyple()
            )
            self.add_segments(response, components=component, files=file)
        if result.errors:
            component, file = self.get_component_for_segment(
                content="\n".join(repr(item) for item in result.errors),
                title="Errors",
                language="ansi",
                display_colour=constants.Colours.soft_red,
            )
            self.add_segments(response, components=component, files=file)

        if result.stdout:
            component, file = self.get_component_for_segment(
                content=result.stdout, title="Stdout", language="ansi", display_colour=constants.Colours.blue
            )
            self.add_segments(response, components=component, files=file)

        if result._:
            component, file = self.get_component_for_segment(
                content="\n".join(repr(item) for item in result._),
                title="Captured output",
                language="ansi",
                display_colour=constants.Colours.soft_orange,
            )
            self.add_segments(response, components=component, files=file)

        response.components.extend(components)
        return response

    @commands.command(name="ieval", aliases=["iexec"], hidden=True)
    async def ieval(self, ctx: commands.Context, *, body: str) -> None:
        """
        Evaluate Python code within the bot context.

        The code is executed as the bot user, with access to the bot instance and the context of the command.
        The result of the last expression is returned, or None if there is no result.
        Only the bot owner can use this command.

        This command also has (though not yet with support to set) options for the following rules:
        - sort_lists: Sort lists in the output for easier reading.
        - pprint_result: Pretty-print the result using `pprint`.
        - dual_await: If the final result is awaitable, await it twice.
        - modify_ast: Modify the AST to assign the result of the last expression to `_`
        """
        rules = (
            EvalRules.pprint_result | EvalRules.modify_return_underscore | EvalRules.dual_await | EvalRules.sort_lists
        )

        global_vars = {
            "author": ctx.author,
            "bot": self.bot,
            "channel": ctx.channel,
            "commands": commands,
            "constants": constants,
            "ctx": ctx,
            "disnake": disnake,
            "guild": ctx.guild,
            "me": ctx.me,
            "message": ctx.message,
            "pprint": rich.pretty.pprint,
            "asyncio": asyncio,
        }
        body = prepare_input(body)
        result = await self.run_code(body, global_vars, rules=rules)
        result = self.make_pretty(result, rules)
        response = self.get_formatted_response(result)

        if ctx.guild is not None and ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            delete_contexts = (ctx.message, None)
        else:
            delete_contexts = (None,)
        response.components += [
            disnake.ui.ActionRow(
                *[DeleteButton(ctx.author.id, allow_manage_messages=False, initial_message=m) for m in delete_contexts]
            )
        ]
        await ctx.send(
            allowed_mentions=disnake.AllowedMentions.none(), components=response.components, files=response.files
        )

    @commands.command(name="repl", hidden=True)
    async def repl(self, ctx: commands.Context) -> None:
        """Start a REPL session in the channel."""
        rules = (
            EvalRules.pprint_result | EvalRules.modify_return_underscore | EvalRules.dual_await | EvalRules.sort_lists
        )
        if self._repl_session.locked():
            await ctx.send("A REPL session is already running. Please cancel it before starting a new one.")
            return

        vars = {
            "author": ctx.author,
            "bot": self.bot,
            "channel": ctx.channel,
            "commands": commands,
            "constants": constants,
            "ctx": ctx,
            "disnake": disnake,
            "guild": ctx.guild,
            "me": ctx.me,
            "message": ctx.message,
            "pprint": rich.pretty.pprint,
            "asyncio": asyncio,
        }
        last_result: Any = None
        async with self._repl_session:
            await ctx.send("Starting REPL session. Type code to evaluate it. Send `exit` or `quit` to exit.")
            while True:
                # first get a message
                try:
                    msg: disnake.Message = await self.bot.wait_for(
                        "message",
                        check=lambda m: m.author == ctx.author
                        and m.channel == ctx.channel
                        and (content := m.content.removeprefix(sys.ps1).strip())
                        and (
                            bool(prepare_input(content, require_fenced=True))
                            or content.lower().removesuffix("()") in ("exit", "quit")
                        ),
                    )
                except asyncio.TimeoutError:
                    await ctx.reply("REPL session timed out.")
                    break
                if msg.content.strip("`").lower() in ("exit", "quit"):
                    await msg.reply("Exiting REPL session.")
                    break
                body = prepare_input(msg.content, require_fenced=True)
                try:
                    result = await self.run_code(body, vars, rules=rules)
                except SystemExit:
                    break

                result = self.make_pretty(result, rules)
                if result.raw_value == last_result:
                    result.raw_value = None
                response = self.get_formatted_response(result)
                response.components += [
                    disnake.ui.ActionRow(
                        *[
                            DeleteButton(ctx.author.id, allow_manage_messages=False, initial_message=m)
                            for m in (ctx.message, None)
                        ]
                    )
                ]
                await ctx.send(
                    allowed_mentions=disnake.AllowedMentions.none(),
                    components=response.components,
                    files=response.files,
                )
                vars = result.local_vars

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Ensure only the owner can run commands in this extension."""
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner("Only the bot owner can use this command.")

        return True


def setup(bot: Monty) -> None:
    """Load the Internal cog."""
    bot.add_cog(cog=InternalEval(bot))
