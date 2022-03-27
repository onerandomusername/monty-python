import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import aiohttp
import disnake
import rapidfuzz
import rapidfuzz.fuzz
import rapidfuzz.process
from bs4 import BeautifulSoup
from disnake import Colour, Embed
from disnake.ext import commands

from monty.bot import Bot
from monty.utils.delete import DeleteView
from monty.utils.html_parsing import _get_truncated_description
from monty.utils.inventory_parser import fetch_inventory
from monty.utils.markdown import DocMarkdownConverter
from monty.utils.messages import wait_for_deletion


log = logging.getLogger(__name__)

ICON_URL = "https://www.python.org/static/opengraph-icon-200x200.png"
BASE_URL = "https://peps.python.org"
BASE_PEP_URL = f"{BASE_URL}/pep-"
INVENTORY_URL = f"{BASE_URL}/objects.inv"


class HeaderParser:
    """Parser for parsing the descriptor headers from the HTML of a pep page."""

    def parse(self, soup: BeautifulSoup) -> dict[str, str]:
        """Parse the provided BeautifulSoup object and return a dict of pep headers."""
        dl = soup.find("dl")
        results = {}
        for dt in dl.find_all("dt"):
            results[dt.text] = dt.find_next_sibling("dd").text

        return results


class PEPHeaders:
    """Parser for getting the headers from the HTML of a pep page."""

    header_tags = ["h2", "h3", "h4", "h5", "h6"]

    def parse(self, soup: BeautifulSoup) -> str:
        """Parse the provided BeautifulSoup object and return a string of headers in the pep's body."""
        headers: dict[tuple[str, str], str] = {}
        for header in soup.find_all(self.header_tags):
            headers[header.text] = header.name

        return headers


class PythonEnhancementProposals(commands.Cog):
    """Cog for displaying information about PEPs."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.peps: Dict[int, str] = {}
        self.autocomplete: dict[str, int] = {}
        # To avoid situations where we don't have last datetime, set this to now.
        self.last_refreshed_peps: datetime = datetime.now()
        self.bot.loop.create_task(self.refresh_peps_urls())

    async def refresh_peps_urls(self) -> None:
        """Refresh PEP URLs listing in every 3 hours."""
        # Wait until HTTP client is available
        await self.bot.wait_until_ready()
        log.trace("Started refreshing PEP URLs.")
        self.last_refreshed_peps = datetime.now()

        package = await fetch_inventory(INVENTORY_URL)
        if package is None:
            log.error("Failed to fetch pep inventory.")
            return

        for item in package.values():
            for name, location, display_name in item:
                if name.startswith("pep-") and len(name) == 8:
                    self.peps[int(name[4:])] = BASE_URL + "/" + location
                    self.autocomplete[display_name] = int(name[4:])

        log.trace("Got PEP URLs listing from Pep sphinx inventory")

    async def validate_pep_number(self, pep_nr: int) -> Optional[Embed]:
        """Validate is PEP number valid. When it isn't, return error embed, otherwise None."""
        if (
            pep_nr not in self.peps
            and (self.last_refreshed_peps + timedelta(minutes=30)) <= datetime.now()
            and len(str(pep_nr)) < 5
        ):
            await self.refresh_peps_urls()

        if pep_nr not in self.peps:
            log.trace(f"PEP {pep_nr} was not found")
            return Embed(
                title="PEP not found",
                description=f"PEP {pep_nr} does not exist.",
                colour=Colour.red(),
            )

        return None

    def generate_pep_embed(self, pep_header: Dict, pep_nr: int) -> Embed:
        """Generate PEP embed based on PEP headers data."""
        # Assemble the embed
        pep_embed = Embed(
            title=f"PEP {pep_nr} - {pep_header['Title']}",
            url=f"{BASE_PEP_URL}{pep_nr:04}",
        )

        pep_embed.set_thumbnail(url=ICON_URL)

        # Add the interesting information
        fields_to_check = ("Status", "Python-Version", "Created", "Type")
        for field in fields_to_check:
            # Check for a PEP metadata field that is present but has an empty value
            # embed field values can't contain an empty string
            if pep_header.get(field):
                pep_embed.add_field(name=field, value=pep_header[field])

        return pep_embed

    async def fetch_pep_info(self, url: str) -> Tuple[dict[str, str], BeautifulSoup]:
        """Fetch the pep information. This is extracted into a seperate function for future use."""
        async with self.bot.http_session.get(url) as response:
            response.raise_for_status()
            pep_content = await response.text()
        soup = await self.bot.loop.run_in_executor(None, BeautifulSoup, pep_content, "lxml")
        pep_header = HeaderParser().parse(soup)
        return pep_header, soup

    async def get_pep_embed(self, pep_nr: int) -> Tuple[Embed, bool]:
        """Fetch, generate and return PEP embed. Second item of return tuple show does getting success."""
        url = self.peps[pep_nr]

        try:
            pep_header, *_ = await self.fetch_pep_info(url)
        except aiohttp.ClientResponseError as e:
            log.trace(f"The user requested PEP {pep_nr}, but the response had an unexpected status code: {e.status}.")
            return (
                Embed(
                    title="Unexpected error",
                    description="Unexpected HTTP error during PEP search. Please let us know.",
                    colour=Colour.red(),
                ),
                False,
            )
        else:
            return self.generate_pep_embed(pep_header, pep_nr), True

    async def get_pep_section_header(self, inter: disnake.CommandInteraction, number: int, header: str) -> None:
        """Get the contents of the provided header in the pep body."""
        error_embed = await self.validate_pep_number(number)
        if error_embed:
            await inter.send(embed=error_embed, ephemeral=True)
            return
        url = self.peps[number]
        tags, soup = await self.fetch_pep_info(url)

        tag = soup.find(PEPHeaders.header_tags, text=header)

        if tag is None:
            await inter.send("Could not find the requested header in the PEP.", ephemeral=True)
            return

        text = _get_truncated_description(tag.parent, DocMarkdownConverter(page_url=url), max_length=750, max_lines=13)
        if not text:
            text = "No description found."

        embed = Embed(
            title=f"PEP {number} - {tags['Title']}",
            description=text,
        )

        if a := tag.find("a"):

            href = a.attrs.get("href")
            if href:
                embed.url = f"{BASE_PEP_URL}{number:04}/{href}"

        embed.set_thumbnail(url=ICON_URL)
        await inter.send(embed=embed)

    @commands.slash_command(name="pep")
    async def pep_command(
        self, inter: disnake.ApplicationCommandInteraction, number: int, header: Optional[str] = None
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

        success = False
        if not (pep_embed := await self.validate_pep_number(number)):
            pep_embed, success = await self.get_pep_embed(number)

        if success:
            view = DeleteView(inter.author, inter)
            if pep_embed.url:
                view.add_item(disnake.ui.Button(style=disnake.ButtonStyle.link, label="Open PEP", url=pep_embed.url))
            await inter.send(embed=pep_embed, view=view)
            self.bot.loop.create_task(wait_for_deletion(inter, view=view))
            log.trace(f"PEP {number} getting and sending finished successfully")
        else:
            await inter.send(embed=pep_embed, ephemeral=True)
            log.trace(f"Getting PEP {number} failed. Error embed sent.")

    @pep_command.autocomplete("number")
    async def pep_number_completion(self, inter: disnake.ApplicationCommandInteraction, query: str) -> dict[str, int]:
        """Completion for pep numbers."""
        if not query:
            # return some fun peps
            interesting_peps = [0, 8, 257, 517, 619, 660]
            resp = {}
            for title, pep in self.autocomplete.items():
                if pep in interesting_peps:
                    resp[title] = pep
            return {x: y for x, y in sorted(resp.items(), key=lambda x: int(x[1]))}

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

        for num, ((title, pep), score, _) in enumerate(processed):
            if num == 0:
                top_score = score

            if top_score > score + 24:
                break

            peps[title] = pep

        return peps

    @pep_command.autocomplete("header")
    async def pep_header_completion(self, inter: disnake.ApplicationCommandInteraction, query: str) -> dict[str, str]:
        """Completion for pep headers."""
        number = inter.filled_options.get("number")
        if number is None:
            return ["No PEP number provided.", "You must provide a valid pep number before providing a header."]
        if number not in self.peps:
            return [f"Cannot find PEP {number}.", "You must provide a valid pep number before providing a header."]

        _, soup = await self.fetch_pep_info(self.peps[number])

        headers = PEPHeaders().parse(soup)

        return list(headers)[:25]


def setup(bot: Bot) -> None:
    """Load the PEP cog."""
    bot.add_cog(PythonEnhancementProposals(bot))
