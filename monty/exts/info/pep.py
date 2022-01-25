import functools
import logging
from datetime import datetime, timedelta
from email.parser import HeaderParser
from io import StringIO
from typing import Dict, Optional, Tuple

import bs4
import disnake
import rapidfuzz
import rapidfuzz.fuzz
import rapidfuzz.process
from disnake import Colour, Embed
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import Tokens
from monty.utils.delete import DeleteView
from monty.utils.messages import wait_for_deletion


log = logging.getLogger(__name__)

ICON_URL = "https://www.python.org/static/opengraph-icon-200x200.png"
BASE_PEP_URL = "http://www.python.org/dev/peps/pep-"
PEPS_LISTING_API_URL = "https://api.github.com/repos/python/peps/contents"
PEP_0 = "https://www.python.org/dev/peps/"
GITHUB_API_HEADERS = {}
if Tokens.github:
    GITHUB_API_HEADERS["Authorization"] = f"token {Tokens.github}"


class PythonEnhancementProposals(commands.Cog):
    """Cog for displaying information about PEPs."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.peps: Dict[int, str] = {}
        self.autocomplete: dict[str, str] = {}
        # To avoid situations where we don't have last datetime, set this to now.
        self.last_refreshed_peps: datetime = datetime.now()
        self.bot.loop.create_task(self.refresh_peps_urls())

    async def refresh_peps_urls(self) -> None:
        """Refresh PEP URLs listing in every 3 hours."""
        # Wait until HTTP client is available
        await self.bot.wait_until_ready()
        log.trace("Started refreshing PEP URLs.")
        self.last_refreshed_peps = datetime.now()

        async with self.bot.http_session.get(PEPS_LISTING_API_URL, headers=GITHUB_API_HEADERS) as resp:
            if resp.status != 200:
                log.warning(f"Fetching PEP URLs from GitHub API failed with code {resp.status}")
                return

            listing = await resp.json()

        log.trace("Got PEP URLs listing from GitHub API")

        for file in listing:
            name = file["name"]
            if name.startswith("pep-") and name.endswith((".rst", ".txt")):
                pep_number = name.replace("pep-", "").split(".")[0]
                self.peps[int(pep_number)] = file["download_url"]

        # add pep 0 for autocomplete.
        log.info("Successfully refreshed PEP URLs listing.")
        log.info("Scraping pep 0 for autocomplete.")
        async with self.bot.http_session.get(PEP_0) as resp:
            if resp.status != 200:
                log.warning(f"Fetching PEP URLs from GitHub API failed with code {resp.status}")
                return
            bs4_partial = functools.partial(bs4.BeautifulSoup, parse_only=bs4.SoupStrainer("tr"))
            soup = await self.bot.loop.run_in_executor(
                None,
                bs4_partial,
                await resp.text(encoding="utf8"),
                "lxml",
            )

        all_ = None
        for x in soup.find_all("tr"):
            td = x.find_all("td", limit=4)
            if len(td) > 3:
                td = td[1:-1]
            if all_ is None:
                all_ = td
            else:
                all_.extend(td)

        self.autocomplete["0: Index of Python Enhancement Proposals"] = "0"
        for a in all_:
            if num := a.find("a"):
                try:
                    _ = int(num.text)
                except ValueError:
                    continue
                title = num.parent.find_next_sibling("td")
                if title:
                    self.autocomplete[f"{num.text}: {title.text}"] = num.text

        self.autocomplete = {k[0]: str(k[1]) for k in sorted(self.autocomplete.items(), key=lambda x: x[1])}

        log.info("Finished scraping pep0.")

    @staticmethod
    def get_pep_zero_embed() -> Embed:
        """Get information embed about PEP 0."""
        pep_embed = Embed(
            title="**PEP 0 - Index of Python Enhancement Proposals (PEPs)**",
            url=PEP_0,
        )
        pep_embed.set_thumbnail(url=ICON_URL)
        pep_embed.add_field(name="Status", value="Active")
        pep_embed.add_field(name="Created", value="13-Jul-2000")
        pep_embed.add_field(name="Type", value="Informational")

        return pep_embed

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
            title=pep_header["Title"],
            url=f"{BASE_PEP_URL}{pep_nr:04}",
            description=f"PEP {pep_nr}",
        )

        pep_embed.set_thumbnail(url=ICON_URL)

        # Add the interesting information
        fields_to_check = ("Status", "Python-Version", "Created", "Type")
        for field in fields_to_check:
            # Check for a PEP metadata field that is present but has an empty value
            # embed field values can't contain an empty string
            if pep_header.get(field, ""):
                pep_embed.add_field(name=field, value=pep_header[field])

        return pep_embed

    async def get_pep_embed(self, pep_nr: int) -> Tuple[Embed, bool]:
        """Fetch, generate and return PEP embed. Second item of return tuple show does getting success."""
        response = await self.bot.http_session.get(self.peps[pep_nr])

        if response.status == 200:
            log.trace(f"PEP {pep_nr} found")
            pep_content = await response.text()

            # Taken from https://github.com/python/peps/blob/master/pep0/pep.py#L179
            pep_header = HeaderParser().parse(StringIO(pep_content))
            return self.generate_pep_embed(pep_header, pep_nr), True
        else:
            log.trace(
                f"The user requested PEP {pep_nr}, but the response had an unexpected status code: {response.status}."
            )
            return (
                Embed(
                    title="Unexpected error",
                    description="Unexpected HTTP error during PEP search. Please let us know.",
                    colour=Colour.red(),
                ),
                False,
            )

    @commands.slash_command(name="pep")
    async def pep_command(self, inter: disnake.ApplicationCommandInteraction, number: str) -> None:
        """
        Fetch information about a PEP.

        Parameters
        ----------
        number: number of the pep, example: 0
        """
        try:
            number = int(number)
        except ValueError:
            await inter.send("You must send an integer pep number.", ephemeral=True)
            return
        # Handle PEP 0 directly because it's not in .rst or .txt so it can't be accessed like other PEPs.
        if number == 0:
            pep_embed = self.get_pep_zero_embed()
            success = True
        else:
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
    async def pep_number_completion(self, inter: disnake.ApplicationCommandInteraction, query: str) -> dict[str, str]:
        """Completion for pep numbers."""
        if not query:
            # return some fun peps
            interesting_peps = [0, 8, 257, 517, 619, 660]
            resp = {}
            for title, pep in self.autocomplete.items():
                if int(pep) in interesting_peps:
                    resp[title] = str(pep)
            return {x: y for x, y in sorted(resp.items(), key=lambda x: int(x[1]))}

        peps: dict[str, int] = {}

        try:
            int(query)
        except ValueError:
            processor = lambda x: x[0]  # noqa: E731
            query = query.lower()
        else:
            processor = lambda x: x[1]  # noqa: E731

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

            peps[title] = str(pep)

        if not len(peps):
            print("nomatch")

        return peps


def setup(bot: Bot) -> None:
    """Load the PEP cog."""
    bot.add_cog(PythonEnhancementProposals(bot))
