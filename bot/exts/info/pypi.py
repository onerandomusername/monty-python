import asyncio
import datetime
import itertools
import logging
import random
import re
from dataclasses import dataclass

import bs4
import disnake
import yarl
from disnake.ext import commands
from disnake.utils import escape_markdown

from bot.bot import Bot
from bot.constants import NEGATIVE_REPLIES, Colours, RedirectOutput
from bot.utils.delete import get_view


BASE_PYPI_URL = "https://pypi.org"
URL = f"{BASE_PYPI_URL}/pypi/{{package}}/json"
PYPI_ICON = "https://cdn.discordapp.com/emojis/766274397257334814.png"

PYPI_COLOURS = itertools.cycle((Colours.yellow, Colours.blue, Colours.white))
MAX_CACHE = 15
ILLEGAL_CHARACTERS = re.compile(r"[^-_.a-zA-Z0-9]+")
INVALID_INPUT_DELETE_DELAY = RedirectOutput.delete_delay
MAX_RESULTS = 15
log = logging.getLogger(__name__)


@dataclass
class Package:
    """Pypi package info."""

    name: str
    version: str
    description: str
    url: str


class PyPi(commands.Cog):
    """Cog for getting information about PyPi packages."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.searches = {}
        self.fetch_lock = asyncio.Lock()

    @commands.slash_command(name="pypi")
    async def pypi(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Useful commands for info about packages on pypi."""
        pass

    @pypi.sub_command(name="package")
    async def pypi_package(self, inter: disnake.ApplicationCommandInteraction, package: str) -> None:
        """
        Provide information about a specific package from PyPI.

        Parameters
        ----------
        package: The package on pypi to get information about.
        """
        embed = disnake.Embed(title=random.choice(NEGATIVE_REPLIES), colour=Colours.soft_red)
        embed.set_thumbnail(url=PYPI_ICON)

        error = True

        if characters := re.search(ILLEGAL_CHARACTERS, package):
            embed.description = f"Illegal character(s) passed into command: '{escape_markdown(characters.group(0))}'"

        else:
            async with self.bot.http_session.get(URL.format(package=package)) as response:
                if response.status == 404:
                    embed.description = "Package could not be found."

                elif response.status == 200 and response.content_type == "application/json":
                    response_json = await response.json()
                    info = response_json["info"]

                    embed.title = f"{info['name']} v{info['version']}"

                    embed.url = info["package_url"]
                    embed.colour = next(PYPI_COLOURS)

                    summary = escape_markdown(info["summary"])

                    # Summary could be completely empty, or just whitespace.
                    if summary and not summary.isspace():
                        embed.description = summary
                    else:
                        embed.description = "No summary provided."

                    error = False

                else:
                    embed.description = "There was an error when fetching your PyPi package."
                    log.trace(f"Error when fetching PyPi package: {response.status}.")

        if error:
            await inter.send(embed=embed, ephemeral=True)

        else:
            await inter.send(embed=embed, view=get_view(inter))

    def parse_pypi_search(self, content: str) -> list[Package]:
        """Parse pypi search results."""
        results = []
        log.debug("Beginning to parse with bs4")
        parsed = bs4.BeautifulSoup(content, "lxml", parse_only=bs4.SoupStrainer("a", class_="package-snippet"))
        log.debug("Finished parsing.")
        log.info(f"len of parse {len(parsed)}")
        # with open
        all_results = parsed.find_all("a", class_="package-snippet", limit=MAX_RESULTS)
        log.info(f"all_results len {len(all_results)}")
        for result in all_results:
            with open("dump.html", "w") as f:
                f.write(str(result))

            name = getattr(result.find(class_="package-snippet__name", recursive=True), "text", None)
            version = getattr(result.find(class_="package-snippet__version", recursive=True), "text", None)

            if not name or not version:
                continue

            description = getattr(result.find("p", class_="package-snippet__description"), "text", None)
            if not description:
                description = ""
            url = BASE_PYPI_URL + result.get("href")
            result = Package(name, version, description.strip(), url)
            results.append(result)

        return results

    async def fetch_pypi_search(self, query: str, *, use_cache: bool = True) -> tuple[list[Package], yarl.URL]:
        """Cache results of searching pypi."""
        if use_cache and query in self.searches:
            return self.searches[query]

        async with self.fetch_lock:

            params = {"q": query}

            async with self.bot.http_session.get(f"{BASE_PYPI_URL}/search", params=params) as resp:
                txt = await resp.text()

            packages = self.parse_pypi_search(txt)

            if len(self.searches) > MAX_CACHE:
                self.searches.popitem()
            self.searches[query] = packages
            return packages, resp.url

    @pypi.sub_command(name="search")
    @commands.cooldown(2, 300, commands.BucketType.user)
    async def pypi_search(
        self,
        inter: disnake.ApplicationCommandInteraction,
        query: str,
        max_results: int = commands.Param(  # noqa: B008
            default=MAX_RESULTS,
            name="max-results",
            description="Max number of results shown.",
            max_value=MAX_RESULTS,
            min_value=1,
        ),
    ) -> None:
        """
        Search pypi for a package.

        Parameters
        ----------
        query: What to search.
        max_results
        """
        await inter.response.defer()

        current_time = datetime.datetime.utcnow()
        packages, query_url = await self.fetch_pypi_search(query)

        embed = disnake.Embed(description="", title=f"PYPI Package Search: {query}")
        embed.url = str(query_url)
        # packages = sorted(packages, key=lambda pack: pack.name)
        for num, pack in enumerate(packages):
            embed.description += (
                f"[**{num+1}. {pack.name}**]({pack.url}) ({pack.version})\n{pack.description or None}\n\n"
            )

        embed.color = next(PYPI_COLOURS)
        embed.timestamp = current_time
        embed.set_footer(text="Requested at:")
        if len(packages) >= max_results:
            embed.description += f"*Only showing the top {max_results} results.*"

        if not len(embed.description):
            embed.description = "Sorry, no results found."

        await inter.send(embed=embed, view=get_view(inter))

    async def cog_slash_command_error(self, inter: disnake.ApplicationCommandInteraction, error: Exception) -> None:
        """TODO: Handle a few local errors until a full error handlers is written."""
        if isinstance(error, commands.CommandOnCooldown):
            error.handled = True
            await inter.response.send_message(str(error), ephemeral=True)
            return
        raise


def setup(bot: Bot) -> None:
    """Load the PyPi cog."""
    bot.add_cog(PyPi(bot))
