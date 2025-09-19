from html import unescape
from urllib.parse import quote_plus

import disnake
from disnake.ext import commands

from monty import bot
from monty.constants import Colours
from monty.errors import APIError, MontyCommandError
from monty.log import get_logger
from monty.utils import responses


logger = get_logger(__name__)


API_ROOT = "https://realpython.com/search/api/v1/"
ARTICLE_URL = "https://realpython.com{article_url}"
SEARCH_URL = "https://realpython.com/search?q={user_search}"


ERROR_EMBED = disnake.Embed(
    title="Error while searching Real Python",
    description="There was an error while trying to reach Real Python. Please try again shortly.",
    color=responses.DEFAULT_FAILURE_COLOUR,
)


class RealPython(commands.Cog, name="Real Python"):
    """User initiated command to search for a Real Python article."""

    def __init__(self, bot: bot.Monty) -> None:
        self.bot = bot

    @commands.command(aliases=["rp"])
    @commands.cooldown(1, 10, commands.cooldowns.BucketType.user)
    async def realpython(self, ctx: commands.Context, *, user_search: str) -> None:
        """Send 5 articles that match the user's search terms."""
        params = {"q": user_search, "limit": 5}
        async with self.bot.http_session.get(url=API_ROOT, params=params) as response:
            if response.status != 200:
                logger.error(f"Unexpected status code {response.status} from Real Python")
                raise APIError(
                    "Real Python",
                    response.status,
                    "Sorry, there was en error while trying to fetch data from the Stackoverflow website. "
                    "Please try again in some time. "
                    "If this issue persists, please report this issue in our support server, see link below.",
                )

            data = await response.json()

        articles = data["results"]

        if len(articles) == 0:
            raise MontyCommandError(
                title=f"No articles found for '{user_search}'",
                message="Try broadening your search to show more results.",
            )

        article_embed = disnake.Embed(
            title="Search results - Real Python",
            url=SEARCH_URL.format(user_search=quote_plus(user_search)),
            description="Here are the top 5 results:",
            color=Colours.orange,
        )

        for article in articles:
            article_embed.add_field(
                name=unescape(article["title"]),
                value=ARTICLE_URL.format(article_url=article["url"]),
                inline=False,
            )
        article_embed.set_footer(text="Click the links to go to the articles.")

        await ctx.send(embed=article_embed)


def setup(bot: bot.Monty) -> None:
    """Load the Real Python Cog."""
    bot.add_cog(RealPython(bot))
