import logging
import re
from random import randint
from typing import Dict, Optional, Union

import disnake
from disnake.ext import commands, tasks

from monty.bot import Bot
from monty.constants import Colours


log = logging.getLogger(__name__)

COMIC_FORMAT = re.compile(r"latest|[0-9]+")
BASE_URL = "https://xkcd.com"


class XKCD(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Retrieving XKCD comics."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.latest_comic_info: Dict[str, Union[str, int]] = {}
        self.get_latest_comic_info.start()

    def cog_unload(self) -> None:
        """Cancels refreshing of the task for refreshing the most recent comic info."""
        self.get_latest_comic_info.cancel()

    @tasks.loop(minutes=30)
    async def get_latest_comic_info(self) -> None:
        """Refreshes latest comic's information ever 30 minutes. Also used for finding a random comic."""
        async with self.bot.http_session.get(f"{BASE_URL}/info.0.json") as resp:
            if resp.status == 200:
                self.latest_comic_info = await resp.json()
            else:
                log.debug(f"Failed to get latest XKCD comic information. Status code {resp.status}")

    @commands.slash_command(name="xkcd")
    async def fetch_xkcd_comics(
        self, inter: disnake.ApplicationCommandInteraction, comic: Optional[str] = None
    ) -> None:
        """
        View an xkcd comic.

        Parameters
        ----------
        comic: number or 'latest'. Leave empty to show a random comic.
        """
        embed = disnake.Embed(title=f"XKCD comic '{comic}'")

        # temporary casting back to a string, until a subcommand is added for latest support
        if comic is not None:
            comic = str(comic)

        embed.colour = Colours.soft_red

        if comic and (comic := re.match(COMIC_FORMAT, comic)) is None:
            embed.description = "Comic parameter should either be an integer or 'latest'."
            await inter.send(embed=embed, ephemeral=True)
            return

        comic = randint(1, self.latest_comic_info["num"]) if comic is None else comic.group(0)

        if comic == "latest":
            info = self.latest_comic_info
        else:
            async with self.bot.http_session.get(f"{BASE_URL}/{comic}/info.0.json") as resp:
                if resp.status == 200:
                    info = await resp.json()
                else:
                    embed.title = f"XKCD comic #{comic}"
                    embed.description = f"{resp.status}: Could not retrieve xkcd comic #{comic}."
                    log.debug(f"Retrieving xkcd comic #{comic} failed with status code {resp.status}.")
                    await inter.send(embed=embed)
                    return

        embed.title = f"XKCD comic #{info['num']}"
        embed.description = info["alt"]
        embed.url = f"{BASE_URL}/{info['num']}"

        if info["img"][-3:] in ("jpg", "png", "gif"):
            embed.set_image(url=info["img"])
            date = f"{info['year']}/{info['month']}/{info['day']}"
            embed.set_footer(text=f"{date} - #{info['num']}, '{info['safe_title']}'")
            embed.colour = Colours.soft_green
        else:
            embed.description = (
                "The selected comic is interactive, and cannot be displayed within an embed.\n"
                f"Comic can be viewed [here](https://xkcd.com/{info['num']})."
            )

        await inter.send(embed=embed)


def setup(bot: Bot) -> None:
    """Load the XKCD cog."""
    bot.add_cog(XKCD(bot))
