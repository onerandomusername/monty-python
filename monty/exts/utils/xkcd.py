import re
from typing import Optional, TypedDict, Union

import disnake
from disnake.ext import commands, tasks

from monty.bot import Monty
from monty.constants import Colours
from monty.errors import APIError
from monty.log import get_logger
from monty.utils import responses
from monty.utils.messages import DeleteButton


log = get_logger(__name__)

COMIC_FORMAT = re.compile(r"latest|[0-9]+")
BASE_URL = "https://xkcd.com"


class XkcdDict(TypedDict):
    num: int
    month: str  # is int of month in string form
    year: str
    day: str
    alt: str
    img: str
    title: str
    safe_title: str


class XKCD(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Retrieving XKCD comics."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.latest_comic_info: Optional[XkcdDict] = None
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
        self, inter: disnake.ApplicationCommandInteraction, comic: Optional[Union[str, int]] = None
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

        embed.colour = responses.DEFAULT_FAILURE_COLOUR

        if comic and (match := re.match(COMIC_FORMAT, comic)) is None:
            raise commands.BadArgument("Comic parameter should either be an integer or 'latest'.")

        if not comic or match.group(0) == "latest":
            if self.latest_comic_info is None:
                raise APIError("xkcd", 500, "Could not fetch the latest comic from XKCD. Please try again later.")
            info = self.latest_comic_info
        else:
            async with self.bot.http_session.get(f"{BASE_URL}/{comic}/info.0.json") as resp:
                if resp.status == 200:
                    info: XkcdDict = await resp.json()
                elif resp.status == 404:
                    # 404 was avoided as an easter egg. We should show an embed for it
                    if comic != "404":
                        raise commands.BadArgument("That comic doesn't exist.")
                    embed.title = f"XKCD comic #{comic}"
                    embed.description = f"{resp.status}: Could not retrieve xkcd comic #{comic}."
                    await inter.send(embed=embed, components=DeleteButton(inter.user))
                    return

                else:
                    log.error(f"XKCD comic could not be fetched. Something went wrong fetching {comic}")

                    raise APIError("xkcd", resp.status, "Could not fetch that comic from XKCD. Please try again later.")

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

        components = DeleteButton(inter.author, allow_manage_messages=False)
        await inter.send(embed=embed, components=components)


def setup(bot: Monty) -> None:
    """Load the XKCD cog."""
    bot.add_cog(XKCD(bot))
