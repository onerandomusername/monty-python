import asyncio
import datetime
import functools
import itertools
import random
import re
from dataclasses import dataclass
from typing import Any

import aiohttp
import bs4
import disnake
import rapidfuzz.distance
import rapidfuzz.process
import readme_renderer.markdown
import readme_renderer.rst
import readme_renderer.txt
import yarl
from cachingutils import LRUMemoryCache, async_cached
from disnake.ext import commands, tasks

from monty.bot import Monty
from monty.constants import Colours, Endpoints, Feature
from monty.errors import MontyCommandError
from monty.log import get_logger
from monty.utils import responses
from monty.utils.caching import redis_cache
from monty.utils.helpers import fromisoformat, maybe_defer, utcnow
from monty.utils.html_parsing import _get_truncated_description
from monty.utils.markdown import DocMarkdownConverter
from monty.utils.messages import DeleteButton


BASE_PYPI_URL = "https://pypi.org"
HTML_URL = f"{BASE_PYPI_URL}/project/{{package}}"
JSON_URL = f"{BASE_PYPI_URL}/pypi/{{package}}/json"
SEARCH_URL = f"{BASE_PYPI_URL}/search"

SIMPLE_INDEX = Endpoints.pypi_simple
TOP_PACKAGES = Endpoints.top_pypi_packages

PYPI_ICON = "https://github.com/pypa/warehouse/raw/main/warehouse/static/images/logo-small.png"

PYPI_COLOURS = itertools.cycle((Colours.yellow, Colours.blue, Colours.white))
MAX_CACHE = 15
ILLEGAL_CHARACTERS = re.compile(r"[^-_.a-zA-Z0-9]+")
MAX_RESULTS = 15

log = get_logger(__name__)

PYPI_API_HEADERS = {"Accept": "application/vnd.pypi.simple.v1+json"}


@dataclass
class Package:
    """Pypi package info."""

    name: str
    version: str
    description: str
    url: str


class PyPI(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Cog for getting information about PyPI packages."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.searches = {}
        self.fetch_lock = asyncio.Lock()

        self.all_packages: set[str] = set()
        self.top_packages: list[str] = []

    async def cog_load(self) -> None:
        """Load the package list on cog load."""
        # create the feature if it doesn't exist
        await self.bot.guild_has_feature(None, Feature.PYPI_AUTOCOMPLETE)

        if self.bot.features[Feature.PYPI_AUTOCOMPLETE.value].enabled is not False:
            # start the task
            self.fetch_package_list.start(use_cache=False)
            # pre-fill the autocomplete once
            await self.fetch_package_list(use_cache=True)
        else:
            log.warning("Not loading pypi autocomplete as the feature is fully disabled.")

    def cog_unload(self) -> None:
        """Remove the autocomplete task on cog unload."""
        self.fetch_package_list.cancel()

    @staticmethod
    def check_characters(package: str) -> re.Match | None:
        """Check if the package is valid."""
        return re.search(ILLEGAL_CHARACTERS, package)

    @redis_cache(
        "pypi-package-list",
        include_posargs=[],
        key_func=lambda *args, **kwargs: "packages",
        skip_cache_func=lambda *args, **kwargs: not kwargs.get("use_cache", True),
        timeout=datetime.timedelta(hours=36),
    )
    async def _fetch_package_list(self, *, use_cache: bool = True) -> tuple[set[str], list[str]]:
        """Fetch all packages from PyPI and cache them."""
        all_packages: set[str] = set()
        top_packages: list[str] = []

        log.debug("Started fetching package list from PyPI.")
        async with self.bot.http_session.get(SIMPLE_INDEX, raise_for_status=True, headers=PYPI_API_HEADERS) as resp:
            json = await resp.json()

        all_packages.update(proj["name"] for proj in json["projects"])
        # fetch the top packages as well, if the endpoint is set
        if TOP_PACKAGES:
            try:
                async with self.bot.http_session.get(TOP_PACKAGES, raise_for_status=True) as resp:
                    json = await resp.json()
            except aiohttp.ClientError:
                log.warning("Could not fetch the top packages.")
            else:
                # limit to the top 300 packages
                try:
                    top_packages.extend([pack["project"] for pack in json["rows"][:300]])
                except Exception:
                    log.exception("Encountered an error with setting the top packages")

        return all_packages, top_packages

    # run this once a day
    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc))
    async def fetch_package_list(self, *, use_cache: bool = True) -> None:
        """Fetch all packages from PyPI and cache them."""
        log.debug("Might fetch packages from PyPI or use cache.")
        all_packages, top_packages = await self._fetch_package_list(use_cache=use_cache)
        self.all_packages.clear()
        self.all_packages.update(all_packages)

        self.top_packages.clear()
        self.top_packages.extend(top_packages)
        log.info("Loaded list of all PyPI packages.")

    async def fetch_package(self, package: str) -> dict[str, Any] | None:
        """Fetch a package from PyPI."""
        async with self.bot.http_session.get(JSON_URL.format(package=package), headers=PYPI_API_HEADERS) as response:
            if response.status == 200 and response.content_type == "application/json":
                return await response.json()
            return None

    @async_cached(cache=LRUMemoryCache(25, timeout=int(datetime.timedelta(hours=2).total_seconds())))
    async def fetch_description(
        self, package: str, description: str, description_content_type: str, max_length: int = 1000
    ) -> str | None:
        """Fetch a description parsed into markdown from PyPI."""
        if description_content_type and description_content_type not in ("text/markdown", "text/x-rst", "text/plain"):
            return f"Unknown description content type {description_content_type!r}."
        if description_content_type.startswith("text/markdown") or description_content_type == "":
            if "variant=CommonMark" in description_content_type:
                variant = "CommonMark"
            else:
                variant = "GFM"
            html = readme_renderer.markdown.render(description, variant=variant)
        elif description_content_type == "text/plain":
            html = readme_renderer.txt.render(description)
        elif description_content_type == "text/x-rst":
            html = readme_renderer.rst.render(description)
        else:
            html = None
        if not html:
            msg = (
                "Unreachable code reached in description parsing. HTML is None."
                " Content type was {description_content_type!r}"
            )
            raise RuntimeError(msg)
        parsed = await self.bot.loop.run_in_executor(None, bs4.BeautifulSoup, html, "lxml")
        text = _get_truncated_description(
            parsed.find("body") or parsed,
            DocMarkdownConverter(page_url=HTML_URL.format(package=package)),
            max_length=max_length,
            max_lines=21,
        )
        return "\n".join([line.rstrip() for line in text.splitlines() if line and not line.isspace()])

    async def make_pypi_components(
        self, package: str, json: dict, *, with_description: bool = False
    ) -> tuple[list[disnake.ui.MessageUIComponent | disnake.ui.Container | disnake.ui.ActionRow], str]:
        """Create components for a package."""
        components: list[disnake.ui.Container] = [
            disnake.ui.Container(accent_colour=disnake.Colour(next(PYPI_COLOURS)))
        ]

        info = json["info"]

        components[0].children.append(
            disnake.ui.TextDisplay(f"### [{info['name']} v{info['version']}]({info['package_url']})")
        )
        short_about = ""

        summary = disnake.utils.escape_markdown(info["summary"])

        # Summary could be completely empty, or just whitespace.
        if summary and not summary.isspace():
            short_about += f"{summary}"
        else:
            short_about += "*No summary provided.*"

        # add some padding
        if not with_description:
            magic_wrap = 20
            rough_lines = (len(short_about) // magic_wrap) + (magic_wrap * short_about.count("\n"))
            while rough_lines < magic_wrap:
                short_about += "\n"
                rough_lines += magic_wrap
        short_about += "\n\n"

        try:
            release_info = json["releases"][info["version"]]
            short_about += (
                f"-# Last updated: {disnake.utils.format_dt(fromisoformat(release_info[0]['upload_time']))}\n"
            )
        except (KeyError, IndexError):
            pass

        components[0].children.append(
            disnake.ui.Section(
                disnake.ui.TextDisplay(short_about.strip()),
                accessory=disnake.ui.Thumbnail(PYPI_ICON),
            )
        )

        if with_description and (description := info["description"]) and description != "UNKNOWN":
            # there's likely a description here, so we're going to fetch the html project page,
            # and parse the html to get the rendered description
            # this means that we don't have to parse the rst or markdown or whatever is the
            # project's description content type
            description = await self.fetch_description(package, description, info["description_content_type"] or "")  # pyright: ignore[reportCallIssue]
            if description:
                components[0].children.append(disnake.ui.TextDisplay(description))

        return list(components), info["package_url"]

    @commands.slash_command(name="pypi")
    async def pypi(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Useful commands for info about packages on PyPI."""

    @pypi.sub_command(name="package")
    async def pypi_package(
        self, inter: disnake.ApplicationCommandInteraction, package: str, with_description: bool = False
    ) -> None:
        """
        Provide information about a specific package from PyPI.

        Parameters
        ----------
        package: The package on PyPI to get information about.
        with_description: Whether or not to show the full description.
        """
        embed = disnake.Embed(title=random.choice(responses.FAILURE_HEADERS), colour=responses.DEFAULT_FAILURE_COLOUR)
        embed.set_thumbnail(url=PYPI_ICON)

        defer_task = None
        if characters := self.check_characters(package):
            msg = f"Illegal character(s) passed into command: '{disnake.utils.escape_markdown(characters.group(0))}'"
            raise MontyCommandError(msg)

        response_json = await self.fetch_package(package)
        if not response_json:
            msg = "Package could not be found."
            raise MontyCommandError(msg)
            # error
        if with_description:
            defer_task = maybe_defer(inter)
        components, url = await self.make_pypi_components(package, response_json, with_description=with_description)

        row = disnake.ui.ActionRow(DeleteButton(inter.author))
        components.append(row)
        if url:
            row.append_item(
                disnake.ui.Button(
                    emoji=disnake.PartialEmoji(name="pypi", id=766274397257334814),
                    style=disnake.ButtonStyle.link,
                    label="View on PyPI",
                    url=url,
                )
            )
        await inter.send(components=components)
        if defer_task:
            defer_task.cancel()

    async def parse_pypi_search(self, content: str) -> list[Package]:
        """Parse PyPI search results."""
        results: list[Package] = []
        log.debug("Beginning to parse with bs4")
        # because run_in_executor only supports args we create a functools partial to be able to pass keyword arguments
        bs_partial = functools.partial(
            bs4.BeautifulSoup, parse_only=bs4.filter.SoupStrainer("a", class_="package-snippet")
        )
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
            url = HTML_URL.format(package=name)
            result = Package(name=str(name), version=str(version), description=description.strip(), url=str(url))
            results.append(result)

        return results

    @async_cached(
        timeout=int(datetime.timedelta(minutes=10).total_seconds()),
        include_posargs=[0, 1],
        include_kwargs=[],
        allow_unset=True,
    )
    async def fetch_pypi_search(self, query: str) -> tuple[list[Package], yarl.URL]:
        """Cache results of searching PyPI."""
        async with self.fetch_lock:
            params = {"q": query}

            # TODO: cache with redis
            async with self.bot.http_session.get(SEARCH_URL, params=params, headers=PYPI_API_HEADERS) as resp:
                txt = await resp.text()

            packages = await self.parse_pypi_search(txt)

            if len(self.searches) > MAX_CACHE:
                self.searches.popitem()
            self.searches[query] = (packages, resp.url)
            return packages, resp.url

    @pypi.sub_command(name="search")
    @commands.cooldown(2, 300, commands.BucketType.user)
    async def pypi_search(
        self,
        inter: disnake.ApplicationCommandInteraction,
        query: str,
        max_results: int = commands.Param(
            default=5,
            name="max-results",
            description="Max number of results shown.",
            max_value=MAX_RESULTS,
            min_value=1,
        ),
    ) -> None:
        """
        Search PyPI for a package.

        Parameters
        ----------
        query: What to search.
        max_results: Max number of results to show.
        """
        defer_task = maybe_defer(inter, delay=2)

        # TODO: fix typing for async_cached
        result: tuple[list[Package], yarl.URL] = await self.fetch_pypi_search(query)  # pyright: ignore[reportCallIssue]
        packages, query_url = result

        embed = disnake.Embed(title=f"PYPI Package Search: {query}")
        description: str = ""
        embed.url = str(query_url)
        # packages = sorted(packages, key=lambda pack: pack.name)
        packages = packages[:max_results]
        for num, pack in enumerate(packages):
            description += f"[**{num + 1}. {pack.name}**]({pack.url}) ({pack.version})\n{pack.description or None}\n\n"

        embed.color = next(PYPI_COLOURS)
        embed.timestamp = utcnow()
        embed.set_footer(text="Requested at:")
        if len(packages) >= max_results:
            description += f"*Only showing the top {max_results} results.*"

        if not len(description):
            description = "Sorry, no results found."
        components = DeleteButton(inter.author)

        embed.description = description
        await inter.send(embed=embed, components=components)
        defer_task.cancel()

    @pypi_package.autocomplete("package")
    async def package_autocomplete(
        self, inter: disnake.CommandInteraction, query: str, *, include_query: bool = False
    ) -> list[str]:
        """Autocomplete package names based on the PyPI index."""
        if not query:
            if self.top_packages:
                the_sample = self.top_packages
            else:
                the_sample = ["Type to begin searching..."]

            # we need to shortcircuit and skip the fuzzing results
            return list(random.sample(the_sample, k=min(25, len(the_sample))))

        if await self.bot.guild_has_feature(inter.guild_id, Feature.PYPI_AUTOCOMPLETE):
            package_list = self.all_packages
        else:
            package_list = self.top_packages
            # include the query as top_packages is not a complete list of packages
            include_query = True

        if not package_list:
            return [query] if query else ["Type to begin searching..."]

        scorer = rapidfuzz.distance.JaroWinkler.similarity
        fuzz_results = rapidfuzz.process.extract(
            query,
            package_list,
            scorer=scorer,
            limit=25,
            score_cutoff=0.4,
        )

        # make the completion
        res = [value for value, score, key in fuzz_results]

        # we need to make sure the query is included and at the top if we're supposed to include it
        if include_query:
            if query in res:
                res.remove(query)
            elif len(res) > 24:
                res.pop()
            res.insert(0, query)
        return res

    pypi_search.autocomplete("query")(functools.partial(package_autocomplete, include_query=True))


def setup(bot: Monty) -> None:
    """Load the PyPI cog."""
    bot.add_cog(PyPI(bot))
