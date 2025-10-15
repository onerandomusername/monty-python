from http import HTTPStatus
from random import choice
from typing import Literal

import disnake
from disnake.ext import commands

from monty.bot import Monty


# why must every single 304 be a large penis
HTTP_URLS: dict[str, list[tuple[str, tuple[int, ...]]]] = {
    "cat": [
        ("https://http.cat/{code}.jpg", ()),
        ("https://httpcats.com/{code}.jpg", ()),
    ],
    "dog": [
        ("https://http.dog/{code}.jpg", (304,)),
        ("https://httpstatusdogs.com/img/{code}.jpg", (304, 308, 422)),
    ],
    "goat": [
        ("https://httpgoats.com/{code}.jpg", (304, 422)),
    ],
}


class HTTPStatusCodes(commands.Cog, name="HTTP Status Codes"):
    """
    Fetch an image depicting HTTP status codes as a dog or a cat or as goat.

    If neither animal is selected a cat or dog or goat is chosen randomly for the given status code.
    """

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

    @commands.group(
        name="http_status",
        aliases=("status", "httpstatus", "http"),
        invoke_without_command=True,
    )
    async def http_status_group(self, ctx: commands.Context, code: int) -> None:
        """Choose an animal randomly for the given status code."""
        subcmd = choice((self.http_cat, self.http_dog, self.http_goat))
        await subcmd(ctx, code)

    async def _fetcher(
        self,
        ctx: commands.Context,
        animal: Literal["cat", "dog", "goat"],
        code: int,
    ) -> None:
        url, ignored_codes = choice(HTTP_URLS[animal])
        if code in ignored_codes:
            # check the other urls for the animal
            for url, ignored_codes in HTTP_URLS[animal]:
                if code not in ignored_codes:
                    url = url
                    break
            else:
                await ctx.send(f"The {animal} does not have an image for status code {code}.")
                return

        embed = disnake.Embed(title=f"**Status: {code}**")
        url = url.format(code=code)
        try:
            HTTPStatus(code)
            async with self.bot.http_session.get(url, allow_redirects=False) as response:
                if response.status == 200:
                    embed.set_image(url=url)
                else:
                    raise NotImplementedError
            embed.set_footer(text=f"Powered by {response.url.host}")

        except ValueError:
            embed.set_footer(text="Inputted status code does not exist.")

        except NotImplementedError:
            embed.set_footer(text=f"Inputted status code is not implemented by {response.url.host} yet.")

        await ctx.send(embed=embed)

    @http_status_group.command(name="cat")
    async def http_cat(self, ctx: commands.Context, code: int) -> None:
        """Sends an embed with an image of a cat, portraying the status code."""
        await self._fetcher(ctx, "cat", code)

    @http_status_group.command(name="dog")
    async def http_dog(self, ctx: commands.Context, code: int) -> None:
        """Sends an embed with an image of a dog, portraying the status code."""
        await self._fetcher(ctx, "dog", code)

    @http_status_group.command(name="goat")
    async def http_goat(self, ctx: commands.Context, code: int) -> None:
        """Sends an embed with an image of a goat, portraying the status code."""
        await self._fetcher(ctx, "goat", code)


def setup(bot: Monty) -> None:
    """Load the HTTPStatusCodes cog."""
    bot.add_cog(HTTPStatusCodes(bot))
