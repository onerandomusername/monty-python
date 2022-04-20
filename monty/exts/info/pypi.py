import asyncio
import datetime
import functools
import itertools
import logging
import random
import re
from dataclasses import dataclass
from typing import Optional

import bs4
import disnake
import yarl
from disnake.ext import commands
from disnake.utils import escape_markdown

from monty.bot import Bot
from monty.constants import NEGATIVE_REPLIES, Colours, RedirectOutput
from monty.utils.html_parsing import _get_truncated_description
from monty.utils.markdown import DocMarkdownConverter
from monty.utils.messages import DeleteView


BASE_PYPI_URL = "https://pypi.org"
HTML_URL = f"{BASE_PYPI_URL}/project/{{package}}"
JSON_URL = f"{BASE_PYPI_URL}/pypi/{{package}}/json"
SEARCH_URL = f"{BASE_PYPI_URL}/search"

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

    @staticmethod
    def check_characters(package: str) -> Optional[re.Match]:
        """Check if the package is valid."""
        return re.search(ILLEGAL_CHARACTERS, package)

    async def fetch_package(self, package: str) -> Optional[str]:
        """Fetch a package from pypi."""
        async with self.bot.http_session.get(JSON_URL.format(package=package)) as response:
            if response.status == 200 and response.content_type == "application/json":
                return await response.json()
            return None

    async def fetch_description(self, package: str, max_length: int = 1000) -> Optional[str]:
        """Fetch a description parsed into markdown from pypi."""
        url = HTML_URL.format(package=package)
        async with self.bot.http_session.get(url) as response:
            if response.status != 200:
                return None
            html = await response.text()
        # because run_in_executor only supports args we create a functools partial to be able to pass keyword arguments
        # parse_only=bs4.SoupStrainer("a", class_="package-snippet")
        bs_partial = functools.partial(
            bs4.BeautifulSoup, parse_only=bs4.SoupStrainer(name="div", attrs={"class": "project-description"})
        )
        parsed = await self.bot.loop.run_in_executor(None, bs_partial, html, "lxml")
        text = _get_truncated_description(
            parsed.find("div", attrs={"class": "project-description"}),
            DocMarkdownConverter(page_url=url),
            max_length=max_length,
            max_lines=21,
        )
        text = "\n".join([line.rstrip() for line in text.splitlines() if line and not line.isspace()])
        return text

    async def make_pypi_embed(self, package: str, json: dict, *, with_description: bool = False) -> disnake.Embed:
        """Create an embed for a package."""
        embed = disnake.Embed()
        embed.set_thumbnail(url=PYPI_ICON)

        info = json["info"]

        embed.title = f"{info['name']} v{info['version']}"

        embed.url = info["package_url"]

        try:
            release_info = json["releases"][info["version"]]
            embed.set_footer(text="Last updated")
            embed.timestamp = datetime.datetime.fromisoformat(release_info[0]["upload_time"]).replace(
                tzinfo=datetime.timezone.utc
            )
        except KeyError:
            pass

        embed.colour = next(PYPI_COLOURS)

        summary = escape_markdown(info["summary"])

        # Summary could be completely empty, or just whitespace.
        if summary and not summary.isspace():
            embed.description = summary
        else:
            embed.description = "*No summary provided.*"

        if with_description and (description := info["description"]):
            if description != "UNKNOWN":
                # there's likely a description here, so we're going to fetch the html project page,
                # and parse the html to get the rendered description
                # this means that we don't have to parse the rst or markdown or whatever is the
                # project's description content type
                description = await self.fetch_description(package)
                if description:
                    embed.description += "\n\n" + description

        return embed

    @commands.slash_command(name="pypi")
    async def pypi(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Useful commands for info about packages on pypi."""
        pass

    @pypi.sub_command(name="package")
    async def pypi_package(
        self, inter: disnake.ApplicationCommandInteraction, package: str, with_description: bool = False
    ) -> None:
        """
        Provide information about a specific package from PyPI.

        Parameters
        ----------
        package: The package on pypi to get information about.
        with_description: Whether or not to show the full description.
        """
        embed = disnake.Embed(title=random.choice(NEGATIVE_REPLIES), colour=Colours.soft_red)
        embed.set_thumbnail(url=PYPI_ICON)

        error = True

        if characters := self.check_characters(package):
            embed.description = f"Illegal character(s) passed into command: '{escape_markdown(characters.group(0))}'"

        else:
            response_json = await self.fetch_package(package)
            if response_json:
                embed = await self.make_pypi_embed(package, response_json, with_description=with_description)
                error = False
            else:
                embed.description = "Package could not be found."

        if error:
            await inter.send(embed=embed, ephemeral=True)
            return

        view = DeleteView(inter.author)
        if embed.url:
            view.add_item(disnake.ui.Button(style=disnake.ButtonStyle.link, label="Open PyPI", url=embed.url))
        await inter.send(embed=embed, view=view)

    async def parse_pypi_search(self, content: str) -> list[Package]:
        """Parse pypi search results."""
        results = []
        log.debug("Beginning to parse with bs4")
        # because run_in_executor only supports args we create a functools partial to be able to pass keyword arguments
        bs_partial = functools.partial(bs4.BeautifulSoup, parse_only=bs4.SoupStrainer("a", class_="package-snippet"))
        parsed = await self.bot.loop.run_in_executor(None, bs_partial, content, "lxml")
        log.debug("Finished parsing.")
        log.info(f"len of parse {len(parsed)}")
        # with open
        all_results = parsed.find_all("a", class_="package-snippet", limit=MAX_RESULTS)
        log.info(f"all_results len {len(all_results)}")
        for result in all_results:

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

            async with self.bot.http_session.get(SEARCH_URL, params=params) as resp:
                txt = await resp.text()

            packages = await self.parse_pypi_search(txt)

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
            default=5,
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
        max_results: Max number of results to show.
        """
        await inter.response.defer()

        current_time = datetime.datetime.now()
        packages, query_url = await self.fetch_pypi_search(query)

        embed = disnake.Embed(description="", title=f"PYPI Package Search: {query}")
        embed.url = str(query_url)
        # packages = sorted(packages, key=lambda pack: pack.name)
        packages = packages[:max_results]
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
        view = DeleteView(inter.author)
        await inter.send(embed=embed, view=view)

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
