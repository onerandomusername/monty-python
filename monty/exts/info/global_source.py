from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Final
from urllib.parse import urldefrag

import disnake
from disnake.ext import commands

from monty.utils.helpers import encode_github_link
from monty.utils.messages import DeleteView


if TYPE_CHECKING:
    from monty.bot import Bot
    from monty.exts.eval import Snekbox

logger = logging.getLogger(__name__)


class GlobalSource(commands.Cog):
    """Global source for python objects."""

    def __init__(self, bot: Bot):
        self.bot = bot
        with open(os.path.dirname(__file__) + "/_global_source_snekcode.py", "r") as f:
            self.code: Final[str] = f.read()

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
            result = await self.snekbox.post_eval(self.code.replace("REPLACE_THIS_STRING_WITH_THE_OBJECT_NAME", object))

        # exit codes:
        # 0: success
        # 1: indeterminate error
        # 2: module not resolvable
        # 3: attribute does not exist
        # 4: invalid characters, not a valid object path
        # 5: dynamically created object
        # 6: is a builtin object, prints module name
        # 7: invalid metadata
        # 8: unsupported package (does not use github)
        text = result["stdout"]
        returncode = result["returncode"]
        link = ""
        if returncode == 0:
            link = text.rsplit("#" * 80)[-1].strip()
            text = f"Source of `{object}`:\n<{link}>"
        elif returncode == 1:
            # generic exception occured
            logger.exception(result["stdout"])
            raise Exception("Snekbox returned an error.")
        elif returncode == 2:
            # module not resolvable
            text = "The module you provided was not resolvable to an installed module."
        elif returncode == 3:
            text = "The attribute you are looking for does not exist. Check for misspellings and try again."
        elif returncode == 4:
            text = "The object path you provided is invalid."
        elif returncode == 5:
            text = "That object exists, but is dynamically created."
        elif returncode == 6:
            text = (
                "`{text}` is a builtin object or implemented in C. "
                "It is not currently possible to get source of those objects."
            )
        elif returncode == 7:
            text = "The metadata for the provided module is invalid."
        elif returncode == 8:
            text = "The provided module is not supported."

        view = DeleteView(ctx.author)
        if link:
            view.add_item(disnake.ui.Button(style=disnake.ButtonStyle.link, url=link, label="Go to Github"))
            custom_id = encode_github_link(link)
            if frag := (urldefrag(link)[1]):
                frag = frag.replace("#", "").replace("L", "")
                num1, num2 = frag.split("-")
                if int(num2) - int(num1) < 20:
                    view.add_item(
                        disnake.ui.Button(style=disnake.ButtonStyle.blurple, label="Expand", custom_id=custom_id)
                    )

        await ctx.reply(
            text,
            allowed_mentions=disnake.AllowedMentions(everyone=False, users=False, roles=False, replied_user=True),
            view=view,
        )


def setup(bot: Bot) -> None:
    """Add the global source cog to the bot."""
    bot.add_cog(GlobalSource(bot))
