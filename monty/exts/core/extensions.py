import functools
import importlib
import importlib.util
import pathlib
import sys
import typing as t
from enum import Enum

import disnake
from disnake.ext import commands

from monty import exts
from monty.bot import Monty
from monty.constants import Client
from monty.log import get_logger
from monty.metadata import ExtMetadata
from monty.utils import scheduling
from monty.utils.extensions import EXTENSIONS, invoke_help_command
from monty.utils.messages import DeleteButton
from monty.utils.pagination import LinePaginator


if t.TYPE_CHECKING:
    import watchfiles


EXT_METADATA = ExtMetadata(core=True, no_unload=True)

log = get_logger(__name__)


UNLOAD_BLACKLIST: set[str] = set()
BASE_PATH_LEN = exts.__name__.count(".")

if t.TYPE_CHECKING:
    Extension = str
else:
    from monty.utils.converters import Extension


class ExtensionStatus(str, Enum):
    """Represents the status of an extension."""

    LOADED = ":green_circle:"
    PARTIALLY_LOADED = ":yellow_circle:"
    UNLOADED = ":red_circle:"


class Action(Enum):
    """Represents an action to perform on an extension."""

    # Need to be partial otherwise they are considered to be function definitions.
    LOAD = functools.partial(Monty.load_extension)
    UNLOAD = functools.partial(Monty.unload_extension)
    RELOAD = functools.partial(Monty.reload_extension)


## determine dependents of a file and reload all dependencies accordingly
RuffDependents = dict[str, list[str]]


def _flatten_dependents(*, dependents: RuffDependents, paths: list[str]) -> list[str]:
    """
    Flatten a ruff dependents dict to a list of files.

    Each file will only appear once, even if multiple files depend on it.
    This is the list of files that need to be reloaded if `single` is changed.
    """
    to_process = paths.copy()
    result = []

    while to_process:
        current_module = to_process.pop()
        if current_module not in result:
            result.append(current_module)
        current_dependents = dependents.get(current_module, [])
        for dependent in current_dependents:
            if dependent in result:
                result.remove(dependent)
                to_process.append(dependent)
                continue

            to_process.append(dependent)
            result.append(dependent)
        if current_module not in result:
            result.append(current_module)

    return result


class Extensions(commands.Cog):
    """Extension management commands."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

        self._unloading_through_autoreload = None

    async def cog_load(self) -> None:
        """Resume autoreload if it is enabled."""
        if self.bot._autoreload_args and self.bot._autoreload_task:
            # remake the task
            if not self.bot._autoreload_task.done():
                # don't immediately cancel so it has a moment to finish the request to the discord channel
                self.bot.loop.call_later(1, self.bot._autoreload_task.cancel)

            self.bot._autoreload_task = scheduling.create_task(self._autoreload_worker(**self.bot._autoreload_args))

    def cog_unload(self) -> None:
        """Cancel the coro on unload."""
        if not self._unloading_through_autoreload and not self.bot._autoreload_args:
            if self.bot._autoreload_task and not self.bot._autoreload_task.done():
                self.bot._autoreload_task.cancel()

    @commands.group(
        name="extensions",
        aliases=("ext", "exts", "c", "cogs"),
        invoke_without_command=True,
    )
    async def extensions_group(self, ctx: commands.Context) -> None:
        """Load, unload, reload, and list loaded extensions."""
        await invoke_help_command(ctx)

    @extensions_group.command(name="load", aliases=("l",))
    async def load_command(self, ctx: commands.Context, *extensions: Extension) -> None:
        r"""
        Load extensions given their fully qualified or unqualified names.

        If '\*' or '\*\*' is given as the name, all unloaded extensions will be loaded.
        """  # noqa: W605
        if not extensions:
            await invoke_help_command(ctx)
            return

        if "*" in extensions or "**" in extensions:
            extensions = tuple(set(EXTENSIONS) - set(self.bot.extensions.keys()))  # type: ignore

        msg = self.batch_manage(Action.LOAD, *extensions)

        components = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.send(msg, components=components)

    @extensions_group.command(name="unload", aliases=("ul",))
    async def unload_command(self, ctx: commands.Context, *extensions: Extension) -> None:
        r"""
        Unload currently loaded extensions given their fully qualified or unqualified names.

        If '\*' or '\*\*' is given as the name, all loaded extensions will be unloaded.
        """  # noqa: W605
        if not extensions:
            await invoke_help_command(ctx)
            return

        # set up the blacklist if it hasn't been loaded yet
        global UNLOAD_BLACKLIST
        if not UNLOAD_BLACKLIST:
            UNLOAD_BLACKLIST = {name for name, ext_meta in EXTENSIONS.items() if ext_meta.no_unload}

        blacklisted = "\n".join(UNLOAD_BLACKLIST & set(extensions))

        if blacklisted:
            msg = f":x: The following extension(s) may not be unloaded:```{blacklisted}```"
        else:
            if "*" in extensions or "**" in extensions:
                extensions = tuple(set(self.bot.extensions.keys()) - UNLOAD_BLACKLIST)  # type: ignore

            msg = self.batch_manage(Action.UNLOAD, *extensions)

        components = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.send(msg, components=components)

    @extensions_group.command(name="reload", aliases=("r",), root_aliases=("reload",))
    async def reload_command(self, ctx: commands.Context, *extensions: Extension) -> None:
        r"""
        Reload extensions given their fully qualified or unqualified names.

        If an extension fails to be reloaded, it will be rolled-back to the prior working state.

        If '\*' is given as the name, all currently loaded extensions will be reloaded.
        If '\*\*' is given as the name, all extensions, including unloaded ones, will be reloaded.
        """  # noqa: W605
        if not extensions:
            await invoke_help_command(ctx)
            return

        if "**" in extensions:
            extensions = tuple(EXTENSIONS)
        elif "*" in extensions:
            extensions = tuple(ext for ext in (set(self.bot.extensions.keys()) | set(extensions)) if ext != "*")

        msg = self.batch_manage(Action.RELOAD, *extensions)

        components = DeleteButton(ctx.author, allow_manage_messages=False, initial_message=ctx.message)
        await ctx.send(msg, components=components)

    @extensions_group.command(name="list", aliases=("all",))
    async def list_command(self, ctx: commands.Context) -> None:
        """
        Get a list of all extensions, including their loaded status.

        Grey indicates that the extension is unloaded.
        Green indicates that the extension is currently loaded.
        """
        embed = disnake.Embed(colour=disnake.Colour.blurple())
        embed.set_author(
            name="Extensions List",
            url=Client.git_repo,
            icon_url=str(self.bot.user.display_avatar.url),
        )

        lines: list[str] = []
        categories = self.group_extension_statuses()
        for category, extensions in sorted(categories.items()):
            # Treat each category as a single line by concatenating everything.
            # This ensures the paginator will not cut off a page in the middle of a category.
            category = category.replace("_", " ").title()
            extensions = "\n".join(sorted(extensions))
            lines.append(f"**{category}**\n{extensions}\n")

        log.debug(f"{ctx.author} requested a list of all cogs. Returning a paginated list.")
        await LinePaginator.paginate(lines, ctx, embed, max_size=1200, empty=False)

    def get_extension_status(self, ext: str) -> ExtensionStatus:
        """
        Gets the status of an extension.

        This is a rudimentary check for whether or not a cog
        from that specific extensions is currently loaded.

        This does not check whether or not an extension exists.
        """
        assert ext in EXTENSIONS, "Extension does not exist."

        if not EXTENSIONS[ext].has_cog:  # we won't be checking for anything if the extension has no cogs
            return (ext in self.bot.extensions and ExtensionStatus.LOADED) or ExtensionStatus.UNLOADED
        if ext not in self.bot.extensions:
            return ExtensionStatus.UNLOADED

        # extension is loaded, now to determine the cog
        def _is_submodule(parent: str, child: str) -> bool:
            return parent == child or child.startswith(parent + ".")

        for cog in self.bot.cogs.values():
            if _is_submodule(ext, cog.__module__):
                return ExtensionStatus.LOADED

        return ExtensionStatus.PARTIALLY_LOADED

    def group_extension_statuses(self) -> t.Mapping[str, list[str]]:
        """Return a mapping of extension names and statuses to their categories."""
        categories: dict[str, list[str]] = {}

        for ext in EXTENSIONS:
            status = self.get_extension_status(ext)

            path = ext.split(".")
            if len(path) > BASE_PATH_LEN + 1:
                category = " - ".join(path[BASE_PATH_LEN:-1])
            else:
                category = "uncategorised"

            categories.setdefault(category, []).append(f"{status}  {path[-1]}")

        return categories

    def batch_manage(self, action: Action, *extensions: str) -> str:
        """
        Apply an action to multiple extensions and return a message with the results.

        If only one extension is given, it is deferred to `manage()`.
        """
        if len(extensions) == 1:
            msg, _ = self.manage(action, extensions[0])
            return msg

        verb = action.name.lower()
        failures = {}

        for extension in extensions:
            _, error = self.manage(action, extension)
            if error:
                failures[extension] = error

        emoji = ":x:" if failures else ":ok_hand:"
        msg = f"{emoji} {len(extensions) - len(failures)} / {len(extensions)} extensions {verb}ed."

        if failures:
            failures = "\n".join(f"{ext}\n    {err}" for ext, err in failures.items())
            msg += f"\nFailures:```{failures}```"

        log.debug(f"Batch {verb}ed extensions.")

        return msg

    def manage(self, action: Action, ext: str) -> t.Tuple[str, t.Optional[str]]:
        """Apply an action to an extension and return the status message and any error message."""
        verb = action.name.lower()
        error_msg = None

        try:
            action.value(self.bot, ext)
        except (commands.ExtensionAlreadyLoaded, commands.ExtensionNotLoaded):
            if action is Action.RELOAD:
                # When reloading, just load the extension if it was not loaded.
                return self.manage(Action.LOAD, ext)

            msg = f":x: Extension `{ext}` is already {verb}ed."
            log.debug(msg[4:])
        except Exception as e:
            e = getattr(e, "original", e)

            log.exception(f"Extension '{ext}' failed to {verb}.")

            error_msg = f"{e.__class__.__name__}: {e}"
            msg = f":x: Failed to {verb} extension `{ext}`:\n```{error_msg}```"
        else:
            msg = f":ok_hand: Extension successfully {verb}ed: `{ext}`."
            log.debug(msg[10:])

        return msg, error_msg

    async def _autoreload_action(
        self,
        *,
        changes: "set[tuple[watchfiles.Change, str]]",
        ext_paths: dict[str, str],
        channel: disnake.abc.Messageable,
        extra_mods_to_path: dict[str, str],
    ) -> None:
        import subprocess  # noqa: F401

        modified_extensions = set()
        extra_path_message = ""
        all_changes = []
        for change in changes:
            if change[1] not in ext_paths:
                for extra_path in extra_mods_to_path:
                    if change[1].startswith(extra_path):
                        relative_path = str(pathlib.Path(change[1]).relative_to(pathlib.Path.cwd()))
                        extra_path_message += relative_path + "\n"

                        break
                else:
                    continue
                try:
                    dependent_process = subprocess.run(
                        ["uv", "run", "ruff", "analyze", "graph", "monty", "-q", "--direction", "dependents"],  # noqa: S607
                        capture_output=True,
                        encoding="utf-8",
                        check=True,
                        cwd=pathlib.Path.cwd(),
                    )
                except Exception as e:
                    log.error(f"Error running ruff analyze graph: {e}")
                    continue
                dependents: RuffDependents = disnake.utils._from_json(dependent_process.stdout)
                res = str(pathlib.Path(extra_path).relative_to(pathlib.Path.cwd()))
                all_changes = _flatten_dependents(
                    dependents=dependents,
                    paths=[res, *all_changes],
                )
                continue
            modified_extensions.add(ext_paths[change[1]])

        for path in all_changes:
            modified_extensions.update(
                ext
                for ext, module in self.bot.extensions.items()
                if module.__file__ and module.__file__.startswith(path)
            )
            # reload all of the modules from all changes
            name = path.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
            if name in self.bot.extensions:
                modified_extensions.add(name)
                continue
            old = sys.modules.pop(name)
            importlib.invalidate_caches()
            try:
                importlib.import_module(name)
            except Exception as e:
                sys.modules[name] = old
                log.exception(f"Error re-importing module {name}: {e}")
                raise

        if __name__ in modified_extensions:
            # we bug out if we try to reload ourselves. It cancels the task
            # this is utterly terrible code
            self._unloading_through_autoreload = True

        msg = self.batch_manage(Action.RELOAD, *modified_extensions)
        if extra_path_message:
            msg += f"\nChanges detected in extra paths:\n```{extra_path_message}```"

        await channel.send("autoreload detected changes::\n" + msg)

    async def _autoreload_worker(self, channel: disnake.abc.Messageable, extra_paths: t.Sequence[str] = ()) -> None:
        import watchfiles

        ext_paths = {module.__file__: extension for extension, module in self.bot.extensions.items() if module.__file__}

        self.bot._autoreload_args = {"channel": channel, "extra_paths": extra_paths}  # add for use in cog_unload

        extra_mods_to_path = {}
        if extra_paths:
            extra_mods_to_path = {}
            for path in extra_paths:
                if pathlib.Path(path).is_dir():
                    extra_mods_to_path.update(
                        {
                            str(p.resolve()): p.stem
                            for p in pathlib.Path(path).rglob("*.py")
                            if p.is_file() and p.stem != "__init__"
                        }
                    )
                else:
                    extra_mods_to_path.update({str(pathlib.Path(path).resolve()): pathlib.Path(path).stem})

        async for changes in watchfiles.awatch(*ext_paths, *extra_mods_to_path):
            try:
                await self._autoreload_action(
                    channel=channel,
                    ext_paths=ext_paths,
                    extra_mods_to_path=extra_mods_to_path,
                    changes=changes,
                )
            except Exception as e:
                log.exception(f"Error in autoreload action: {e}")
                await channel.send(f"Error in autoreload action: {e}")

    # developer autoreloading
    @extensions_group.group(
        name="autoreload",
        aliases=("ar",),
        invoke_without_command=True,
    )
    async def autoreload(self, ctx: commands.Context) -> None:
        """
        Autoreload of modified extensions.

        This watches for file edits, and will reload modified extensions automatically.
        """
        msg = "Autoreload is currently: "
        msg += "enabled" if self.bot._autoreload_task and not self.bot._autoreload_task.done() else "disabled"
        msg += "."
        await ctx.send(msg)

    @autoreload.command(name="enable")
    async def enable_autoreload(self, ctx: commands.Context, *extra_paths: str) -> None:
        """Enable extension autoreload."""
        if not importlib.util.find_spec("watchfiles"):
            raise RuntimeError("Watchfiles not installed. Command not usable.")

        if extra_paths:
            for path in extra_paths:
                if not pathlib.Path(path).is_file():
                    raise commands.BadArgument(f"Extra path '{path}' is not a valid file.")
        else:
            extra_paths += (
                "monty/utils",
                "monty/metadata.py",
                "monty/config_metadata.py",
            )

        msg = ""
        if self.bot._autoreload_task:
            self.bot._autoreload_task.cancel()
            msg = "Cancelling previous autoreload task. Starting a new one."

        self.bot._autoreload_task = scheduling.create_task(
            self._autoreload_worker(ctx.channel, extra_paths=extra_paths)
        )
        if not msg:
            msg += "\nEnabled autoreload task!"
        if extra_paths:
            msg += f" Watching extra paths: `{'`, `'.join(extra_paths)}`"
        await ctx.send(msg)

    @autoreload.command(name="disable")
    async def disable_autoreload(self, ctx: commands.Context) -> None:
        """Disable extension autoreload."""
        if not self.bot._autoreload_task:
            raise commands.BadArgument("Reload was already off.")

        if not self.bot._autoreload_task.done():
            self.bot._autoreload_task.cancel()
        self.bot._autoreload_args = None
        await ctx.send("Disabled autoreload task!")

    # This cannot be static (must have a __func__ attribute).
    async def cog_check(self, ctx: commands.Context) -> bool:
        """Only allow moderators and core developers to invoke the commands in this cog."""
        return await self.bot.is_owner(ctx.author)


def setup(bot: Monty) -> None:
    """Load the Extensions cog."""
    bot.add_cog(Extensions(bot))
