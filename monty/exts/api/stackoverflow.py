from html import unescape
from urllib.parse import quote_plus

import disnake
from disnake.ext import commands

from monty import bot
from monty.constants import Colours, Emojis
from monty.errors import APIError, MontyCommandError
from monty.log import get_logger


logger = get_logger(__name__)

BASE_URL = "https://api.stackexchange.com/2.2/search/advanced"
SO_PARAMS = {"order": "desc", "sort": "activity", "site": "stackoverflow"}
SEARCH_URL = "https://stackoverflow.com/search?q={query}"


class Stackoverflow(commands.Cog, name="Stack Overflow", slash_command_attrs={"dm_permission": False}):
    """Contains command to interact with stackoverflow from disnake."""

    def __init__(self, bot: bot.Monty) -> None:
        self.bot = bot

    @commands.command(aliases=["so"])
    @commands.cooldown(1, 15, commands.cooldowns.BucketType.user)
    async def stackoverflow(self, ctx: commands.Context, *, search_query: str) -> None:
        """Sends the top 5 results of a search query from stackoverflow."""
        params = SO_PARAMS | {"q": search_query}
        async with ctx.typing():
            async with self.bot.http_session.get(url=BASE_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                else:
                    logger.error(f"Status code is not 200, it is {response.status}")
                    raise APIError(
                        "Stack Overflow",
                        response.status,
                        "Sorry, there was an error while trying to fetch data from the StackOverflow website. "
                        "Please try again in some time. "
                        "If this issue persists, please report this issue in our support server, see link below.",
                    )
            if not data["items"]:
                raise MontyCommandError(
                    title="No results found",
                    message=f"No search results found for `{search_query}`. "
                    "Try adjusting your search or searching for fewer terms.",
                )

            top5 = data["items"][:5]
            encoded_search_query = quote_plus(search_query)
            embed = disnake.Embed(
                title="Search results - Stackoverflow",
                url=SEARCH_URL.format(query=encoded_search_query),
                description=f"Here are the top {len(top5)} results:",
                color=Colours.orange,
            )
            embed.check_limits()

            for item in top5:
                embed.add_field(
                    name=unescape(item["title"]),
                    value=(
                        f"[{Emojis.reddit_upvote} {item['score']}    "
                        f"{Emojis.stackoverflow_views} {item['view_count']}     "
                        f"{Emojis.reddit_comments} {item['answer_count']}   "
                        f"{Emojis.stackoverflow_tag} {', '.join(item['tags'][:3])}]"
                        f"({item['link']})"
                    ),
                    inline=False,
                )
                try:
                    embed.check_limits()
                except ValueError:
                    embed.remove_field(-1)
                    break

            embed.set_footer(text="View the original link for more results.")

        await ctx.send(embed=embed)


def setup(bot: bot.Monty) -> None:
    """Load the Stackoverflow Cog."""
    bot.add_cog(Stackoverflow(bot))
