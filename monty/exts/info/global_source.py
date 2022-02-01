from __future__ import annotations

from typing import TYPE_CHECKING

import disnake
from disnake.ext import commands


if TYPE_CHECKING:
    from monty.bot import Bot
    from monty.exts.eval import Snekbox

SNEKBOX_CODE = """
import importlib.metadata
import inspect
import pathlib
import pkgutil
import sys

# establish the object itself
try:
    src = pkgutil.resolve_name("{object}")
except ModuleNotFoundError:
    print("Sorry, I can't resolve that module.")
    sys.exit(1)
except AttributeError:
    print("That object doesn't exist.")
    sys.exit(1)
except Exception:
    raise

# get the source of the object
try:
    filename = inspect.getsourcefile(src)
except TypeError:
    print("Cannot get source for a dynamically-created or builtin object.")
    sys.exit(1)
if not inspect.ismodule(src):
    lines, first_line_no = inspect.getsourcelines(src)
    lines_extension = f"#L{{first_line_no}}-L{{first_line_no+len(lines)-1}}"
else:
    lines_extension = ""

module_name = src.__name__ if inspect.ismodule(src) else src.__module__
top_module_name = module_name.split(".", 1)[0]

# determine the actual file name
filename = str(
    pathlib.Path(filename).relative_to(
        pathlib.Path(
            inspect.getsourcefile(importlib.import_module(top_module_name))
        ).parent.parent
    )
)

# get the version and link to the source of the module
if top_module_name in sys.stdlib_module_names:
    if top_module_name in sys.builtin_module_names:
        print(f"`{{module_name}}` is a builtin module.")
        sys.exit(1)
    # handle the object being part of the stdlib
    url = f"https://github.com/python/cpython/blob/3.10/Lib/{{filename}}{{lines_extension}}"
else:
    # assume that the source is github
    try:
        metadata = importlib.metadata.metadata(top_module_name)
    except importlib.metadata.PackageNotFoundError:
        print(f"Sorry, I can't find the metadata for `{{module_name}}`.")
        sys.exit(1)
    # print(metadata.keys())
    version = metadata["Version"]
    for url in [metadata.get("Home-page"), *metadata.json["project_url"]]:
        url = url.split(",", 1)[-1].strip()
        if url.startswith("https://github.com/"):
            break
    else:
        print("This package isn't supported right now.")
        sys.exit(1)
    if top_module_name != "arrow":
        version = f"v{{version}}"
    url += f"/blob/{{version}}/{{filename}}{{lines_extension}}"
print("<" + url + ">")
"""


class GlobalSource(commands.Cog):
    """Global source for python objects."""

    def __init__(self, bot: Bot):
        self.bot = bot

    @property
    def snekbox(self) -> Snekbox:
        """Return the snekbox cog where the code is ran."""
        if snekbox := self.bot.get_cog("Snekbox"):
            return snekbox
        raise RuntimeError("Snekbox is not loaded")

    @commands.command(name="globalsource", aliases=("gs",), hidden=True)
    async def globalsource(self, ctx: commands.Context, object: str) -> None:
        """Get the source of a python object."""
        async with ctx.typing():
            result = await self.snekbox.post_eval(SNEKBOX_CODE.format(object=object))
        await ctx.send(result["stdout"] or "No output.", allowed_mentions=disnake.AllowedMentions.none())


def setup(bot: Bot) -> None:
    """Add the global source cog to the bot."""
    bot.add_cog(GlobalSource(bot))
