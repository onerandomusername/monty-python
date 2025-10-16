import dataclasses
import functools
from datetime import datetime, timedelta, timezone
from typing import ClassVar, Literal, cast
from urllib.parse import urljoin

import bs4
import disnake
import rapidfuzz
import rapidfuzz.fuzz
import rapidfuzz.process
from bs4 import BeautifulSoup
from cachingutils import LRUMemoryCache, async_cached
from disnake.ext import commands, tasks

from monty.bot import Monty
from monty.errors import MontyCommandError
from monty.log import get_logger
from monty.utils import scheduling
from monty.utils.helpers import utcnow
from monty.utils.html_parsing import _get_truncated_description
from monty.utils.markdown import DocMarkdownConverter
from monty.utils.messages import DeleteButton


log = get_logger(__name__)

ICON_URL = "https://www.python.org/static/opengraph-icon-200x200.png"
API_URL = "https://peps.python.org/api/peps.json"


# the values below each exist on the api as documented at https://peps.python.org/api/
# this schema should be kept in sync with that api
# to save on memory, fields not currently used are commented out.
# if you need them, uncomment them.
@dataclasses.dataclass(kw_only=True, frozen=True)
class PEPInfo:
    number: int
    title: str
    # authors: str
    # discussions_to: str | None = None
    status: Literal[
        "Accepted",
        "Active",
        "Deferred",
        "Draft",
        "Final",
        "Provisional",
        "Rejected",
        "Superseded",
        "Withdrawn",
    ]
    type: Literal["Informational", "Process", "Standards Track"]
    # topic: Literal["governance", "packaging", "release", "typing", ""]
    created: str
    python_version: str | None
    # post_history: str | None
    # resolution: str | None
    # requires: str | None
    # replaces: str | None
    # superseded_by: str | None
    # author_names: list[str]
    url: str

    def __hash__(self) -> int:
        return hash(hash(type(self)) + self.number)


class PEPHeaders:
    """Parser for getting the headers from the HTML of a pep page."""

    header_tags: ClassVar[list[str]] = ["h2", "h3", "h4", "h5", "h6"]

    def parse(self, soup: BeautifulSoup) -> dict[str, str]:
        """Parse the provided BeautifulSoup object and return a dict of PEP header to body."""
        headers: dict[str, str] = {}
        for header in soup.find_all(self.header_tags):
            headers[header.text] = header.name

        headers.pop("Contents", None)

        return headers


class PythonEnhancementProposals(
    commands.Cog,
    name="PEPs",
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Cog for displaying information about PEPs."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.peps: dict[int, PEPInfo] = {}
        self.autocomplete: dict[str, int] = {}
        # To avoid situations where we don't have last datetime, set this to now.
        self.last_refreshed_peps: datetime = utcnow()
        scheduling.create_task(self.refresh_peps_urls())
        self.refresh_peps_urls.start()

    @tasks.loop(hours=3)
    async def refresh_peps_urls(self) -> None:
        """Refresh PEP URLs listing in every 3 hours."""
        # Wait until HTTP client is available
        await self.bot.wait_until_ready()
        log.trace("Started refreshing PEP URLs.")

        async with self.bot.http_session.get(API_URL) as response:
            response.raise_for_status()
            peps = await response.json()

        self.last_refreshed_peps = utcnow()
        new_peps: dict[int, PEPInfo] = {}
        new_autocomplete: dict[str, int] = {}
        fields = frozenset(field.name for field in dataclasses.fields(PEPInfo))
        for pep_data in peps.values():
            for field in list(pep_data):
                if field not in fields:
                    pep_data.pop(field)
            pep_info = PEPInfo(**pep_data)
            new_peps[pep_info.number] = pep_info
            new_autocomplete[f"PEP {pep_info.number} \u2013 {pep_data['title']}"] = pep_info.number
        self.peps.clear()
        self.peps.update(new_peps)
        self.autocomplete.clear()
        self.autocomplete.update(new_autocomplete)

        log.trace("Got PEP URLs listing from Pep sphinx inventory")

    async def validate_pep_number(self, pep_nr: int) -> PEPInfo:
        """Validate is PEP number valid. When it isn't, return error embed, otherwise None."""
        if (
            pep_nr not in self.peps
            and (self.last_refreshed_peps + timedelta(minutes=30)) <= utcnow()
            and len(str(pep_nr)) < 5
        ):
            await self.refresh_peps_urls()

        if pep_nr not in self.peps:
            log.trace(f"PEP {pep_nr} was not found")
            raise MontyCommandError(
                title="PEP not found",
                message=f"PEP {pep_nr} does not exist.",
            )

        return self.peps[pep_nr]

    def generate_pep_embed(self, pep_info: PEPInfo) -> disnake.Embed:
        """Generate PEP embed based on PEP headers data."""
        # Assemble the embed
        pep_embed = disnake.Embed(
            title=f"PEP {pep_info.number} - {pep_info.title}",
            url=self.peps[pep_info.number].url,
        )

        pep_embed.set_thumbnail(url=ICON_URL)

        # Add the interesting information
        fields_to_check = {
            "Status": pep_info.status,
            "Python-Version": pep_info.python_version,
            "Created": pep_info.created,
            "Type": pep_info.type,
        }
        for field, value in fields_to_check.items():
            if value:
                pep_embed.add_field(name=field, value=value, inline=True)

        return pep_embed

    @async_cached(cache=LRUMemoryCache(25, timeout=int(timedelta(hours=2).total_seconds())))
    async def fetch_pep_soup(self, pep_info: PEPInfo) -> BeautifulSoup:
        """Fetch the pep information. This is extracted into a seperate function for future use."""
        async with self.bot.http_session.get(pep_info.url) as response:
            response.raise_for_status()
            pep_content = await response.text()

        return await self.bot.loop.run_in_executor(None, BeautifulSoup, pep_content, "lxml")

    async def get_pep_section_header(self, inter: disnake.CommandInteraction, number: int, header: str) -> None:
        """Get the contents of the provided header in the pep body."""
        await self.validate_pep_number(number)

        pep_info = self.peps[number]
        soup = cast(
            "BeautifulSoup",
            await self.fetch_pep_soup(pep_info),  # pyright: ignore[reportCallIssue]
        )

        tag: bs4.element.Tag | None = await self.bot.loop.run_in_executor(
            None, functools.partial(soup.find, PEPHeaders.header_tags, text=header)
        )

        if tag is None or not tag.parent:
            msg = "Could not find the requested header in the PEP."
            raise MontyCommandError(msg)

        text = _get_truncated_description(
            tag.parent, DocMarkdownConverter(page_url=pep_info.url), max_length=750, max_lines=14
        )
        text = (text.lstrip() + "\n").split("\n", 1)[-1].strip()
        if not text:
            msg = "No text found for that header."
            raise MontyCommandError(msg)

        embed = disnake.Embed(
            title=header,
            description=text,
        )
        embed.set_author(name=f"PEP {number} - {pep_info.title}", url=pep_info.url)

        if tag.a and (href := tag.a.get("href")):
            embed.url = urljoin(pep_info.url, str(href))

        embed.set_thumbnail(url=ICON_URL)
        embed.set_footer(text="PEP Created")
        embed.timestamp = datetime.strptime(pep_info.created, "%d-%b-%Y").replace(tzinfo=timezone.utc)

        components = [
            DeleteButton(inter.author),
            disnake.ui.Button(style=disnake.ButtonStyle.link, label="Open PEP", url=embed.url or pep_info.url),
        ]
        await inter.send(embed=embed, components=components)

    @commands.slash_command(name="pep")
    async def pep_command(
        self,
        inter: disnake.ApplicationCommandInteraction,
        number: int,
        header: str | None = None,
    ) -> None:
        """
        Fetch information about a PEP.

        Parameters
        ----------
        number: number or search query
        header: If provided, shows a snippet of the PEP at this header.
        """
        if header:
            await self.get_pep_section_header(inter, number, header)
            return

        pep_info = await self.validate_pep_number(number)
        pep_embed = self.generate_pep_embed(pep_info)

        components: list[disnake.ui.Button] = [DeleteButton(inter.author)]
        if pep_embed.url:
            components.append(disnake.ui.Button(style=disnake.ButtonStyle.link, label="Open PEP", url=pep_embed.url))
        await inter.send(embed=pep_embed, components=components)
        log.trace(f"PEP {number} getting and sending finished successfully")

    @pep_command.autocomplete("number")
    async def pep_number_completion(self, inter: disnake.ApplicationCommandInteraction, query: str) -> dict[str, int]:
        """Completion for pep numbers."""
        if not query:
            # return some interesting peps
            interesting_peps = [0, 8, 257, 517, 621, 660, 745, 790]
            resp = {title: pep for title, pep in self.autocomplete.items() if pep in interesting_peps}
            return dict(sorted(resp.items(), key=lambda x: int(x[1])))

        peps: dict[str, int] = {}

        try:
            int(query)
        except ValueError:
            processor = lambda x: x[0]  # noqa: E731
            query = query.lower()
        else:
            processor = lambda x: str(x[1])  # noqa: E731

        processed = rapidfuzz.process.extract(
            (query, query),
            self.autocomplete.items(),
            scorer=rapidfuzz.fuzz.ratio,
            processor=processor,
            limit=11,
            score_cutoff=0,
        )
        top_score = 0
        for num, ((title, pep), score, _) in enumerate(processed):
            if num == 0:
                top_score = score

            if top_score > score + 24:
                break

            peps[title] = pep

        return peps

    @pep_command.autocomplete("header")
    async def pep_header_completion(
        self, inter: disnake.ApplicationCommandInteraction, query: str
    ) -> dict[str, str] | list[str]:
        """Completion for pep headers."""
        number = cast("int | None", inter.filled_options.get("number"))
        if number is None:
            return ["No PEP number provided.", "You must provide a valid pep number before providing a header."]
        if number not in self.peps:
            return [f"Cannot find PEP {number}.", "You must provide a valid pep number before providing a header."]

        soup = await self.fetch_pep_soup(self.peps[number])  # pyright: ignore[reportCallIssue]

        headers = PEPHeaders().parse(soup)

        if not query:
            return list(headers)[:25]

        completion = []
        query = query.lower().strip()
        for header in headers:
            if query in header.lower():
                completion.append(header)
            if len(completion) >= 25:
                break

        return completion


def setup(bot: Monty) -> None:
    """Load the PEP cog."""
    bot.add_cog(PythonEnhancementProposals(bot))
