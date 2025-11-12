import importlib
import inspect
import pkgutil
from collections.abc import Generator
from typing import TYPE_CHECKING, NoReturn

from disnake.ext import commands

from monty import exts
from monty.log import get_logger


if TYPE_CHECKING:
    from monty.metadata import ExtMetadata

log = get_logger(__name__)


def unqualify(name: str) -> str:
    """Return an unqualified name given a qualified module/package `name`."""
    return name.rsplit(".", maxsplit=1)[-1]


def walk_extensions() -> Generator[tuple[str, "ExtMetadata"], None, None]:
    """Yield extension names from monty.exts subpackage."""
    from monty.metadata import ExtMetadata

    def on_error(name: str) -> NoReturn:
        raise ImportError(name=name)  # pragma: no cover

    skip_modules: set[str] = set()

    for module in pkgutil.walk_packages(exts.__path__, f"{exts.__name__}.", onerror=on_error):
        if unqualify(module.name).startswith("_") or module.name in skip_modules:
            # Ignore module/package names starting with an underscore.
            continue

        imported = importlib.import_module(module.name)
        if not inspect.isfunction(getattr(imported, "setup", None)):
            # If it lacks a setup function, it's not an extension.
            continue

        # This check only excludes init files which add an extension.
        if module.name.endswith(".__init__"):
            # Add all submodules to skip list to avoid re-processing.
            skip_modules.add(module.name)

        ext_metadata = getattr(imported, "EXT_METADATA", None)
        if ext_metadata is not None:
            if not isinstance(ext_metadata, ExtMetadata):
                if ext_metadata == ExtMetadata:
                    log.info(
                        f"{module.name!r} seems to have passed the ExtMetadata class directly to "
                        "EXT_METADATA. Using defaults."
                    )
                else:
                    log.error(
                        f"Extension {module.name!r} contains an invalid EXT_METADATA variable. "
                        "Loading with metadata defaults."
                    )
                yield module.name, ExtMetadata()
                continue

            yield module.name, ext_metadata
            continue

        log.trace(f"Extension {module.name!r} is missing an EXT_METADATA variable. Assuming its a normal extension.")

        # Presume Production Mode/Metadata defaults if metadata var does not exist.
        yield module.name, ExtMetadata()


async def invoke_help_command(ctx: commands.Context) -> None:
    """Invoke the help command or default help command if help extensions is not loaded."""
    if ctx.bot.get_cog("Help"):
        help_command = ctx.bot.get_command("help")
        await ctx.invoke(help_command, ctx.command.qualified_name)  # type: ignore
        return
    await ctx.send_help(ctx.command)


EXTENSIONS: dict[str, "ExtMetadata"] = {}
