import random
from typing import Any, TypedDict

import disnake
from disnake.ext import commands, tasks
from typing_extensions import NotRequired

from monty.bot import Monty
from monty.constants import Colours
from monty.errors import APIError
from monty.log import get_logger
from monty.utils import responses
from monty.utils.messages import DeleteButton


log = get_logger(__name__)

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
    extra_parts: NotRequired[dict[str, Any]]


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
        self.latest_comic_info: XkcdDict | None = None
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
    async def xkcd(self, _: disnake.ApplicationCommandInteraction) -> None:
        """View an xkcd comic."""

    async def send_xkcd(self, inter: disnake.ApplicationCommandInteraction, info: XkcdDict) -> None:
        """Parse an xkcd API response into a component."""
        date = f"{info['year']}/{info['month']}/{info['day']}"
        if info["img"][-3:] in ("jpg", "png", "gif") and not info.get("extra_parts"):
            await inter.send(
                components=[
                    disnake.ui.Container(
                        disnake.ui.TextDisplay(f"### [XKCD comic #{info['num']}]({BASE_URL}/{info['num']})"),
                        disnake.ui.TextDisplay(info["alt"]),
                        disnake.ui.MediaGallery(disnake.MediaGalleryItem(info["img"])),
                        disnake.ui.TextDisplay(f"{date} - #{info['num']}, '{info['safe_title']}'"),
                        accent_colour=disnake.Colour(Colours.soft_green),
                    ),
                    DeleteButton(inter.author, allow_manage_messages=False),
                ]
            )
        else:
            await inter.send(
                components=[
                    disnake.ui.Container(
                        disnake.ui.TextDisplay(f"### [XKCD comic #{info['num']}]({BASE_URL}/{info['num']})"),
                        disnake.ui.TextDisplay(
                            "The selected comic is interactive, and cannot be displayed within an embed.\n"
                            f"Comic can be viewed [here](https://xkcd.com/{info['num']})."
                        ),
                        disnake.ui.TextDisplay(f"{date} - #{info['num']}, '{info['safe_title']}'"),
                        accent_colour=disnake.Colour(Colours.soft_green),
                    ),
                    DeleteButton(inter.author, allow_manage_messages=False),
                ]
            )

    @xkcd.sub_command()
    async def latest(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """View the latest xkcd comic."""
        if self.latest_comic_info is None:
            msg = "Could not fetch the latest comic from XKCD. Please try again later."
            raise APIError(msg, status_code=500, api="XKCD")

        await self.send_xkcd(inter, self.latest_comic_info)

    @xkcd.sub_command()
    async def number(self, inter: disnake.ApplicationCommandInteraction, comic: int) -> None:
        """
        View an xkcd comic by its number.

        Parameters
        ----------
        comic: The number of the comic to view.
        """
        async with self.bot.http_session.get(f"{BASE_URL}/{comic}/info.0.json") as resp:
            if resp.status == 200:
                info: XkcdDict = await resp.json()
            elif resp.status == 404:
                # xkcd #404 returns a 404 code as an easter egg, so there should be a different message
                if comic != 404:
                    msg = "That comic doesn't exist"
                    raise commands.BadArgument(msg)

                await inter.send(
                    components=[
                        disnake.ui.Container(
                            disnake.ui.TextDisplay(f"### XKCD comic #{comic}"),
                            disnake.ui.TextDisplay("f{resp.status}: Could not retrieve xkcd comic #{comic}"),
                            accent_colour=responses.DEFAULT_FAILURE_COLOUR,
                        )
                    ]
                )
                return
            else:
                log.error(f"XKCD comic could not be fetched. Something went wrong fetching {comic}")

                msg = "Could not fetch that comic from XKCD. Please try again later."
                raise APIError(
                    msg,
                    api="XKCD",
                    status_code=resp.status,
                )

        await self.send_xkcd(inter, info)

    @xkcd.sub_command()
    async def random(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """View a random xkcd comic."""
        if self.latest_comic_info is None:
            msg = "Could not fetch a random comic from XKCD. Please try again later."
            raise APIError(msg, status_code=500, api="XKCD")

        while (comic := random.randint(1, self.latest_comic_info["num"])) == 404:
            ...

        async with self.bot.http_session.get(f"{BASE_URL}/{comic}/info.0.json") as resp:
            if resp.status == 200:
                info: XkcdDict = await resp.json()
            else:
                log.error(f"XKCD comic could not be fetched. Something went wrong fetching {comic}")

                msg = "Could not fetch a random comic from XKCD. Please try again later."
                raise APIError(
                    msg,
                    api="XKCD",
                    status_code=resp.status,
                )

        await self.send_xkcd(inter, info)


def setup(bot: Monty) -> None:
    """Load the XKCD cog."""
    bot.add_cog(XKCD(bot))
