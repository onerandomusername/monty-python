import asyncio
import datetime
import itertools
import json
import pathlib
from typing import Any, Optional

import attrs
import disnake
import rapidfuzz.fuzz
import rapidfuzz.process
from disnake.ext import commands, tasks

import monty.resources
from monty.bot import Monty
from monty.log import get_logger
from monty.utils.helpers import utcnow
from monty.utils.messages import DeleteButton


logger = get_logger(__name__)


RUFF_RULES = monty.resources.folder / "ruff_rules.json"

RUFF_RULES_BASE_URL = "https://docs.astral.sh/ruff/rules"

RUFF_COLOUR_CYCLE = itertools.cycle((0xD7FF66, 0x30173D))


@attrs.define(hash=True, frozen=True)
class Rule:
    name: str
    code: str
    linter: str
    summary: str
    message_formats: tuple[str] = attrs.field(converter=tuple)  # type: ignore
    fix: str
    explanation: str
    preview: bool

    @property
    def title(self) -> str:
        """Return a human-readable title."""
        return self.code + ": " + self.name


class Ruff(commands.Cog):
    """Cog for getting information about Ruff and other rules."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.fetch_lock = asyncio.Lock()

        self.rules: dict[str, Rule] = {}

        self.last_fetched: Optional[datetime.datetime] = None

    async def cog_load(self) -> None:
        """Load the rules on cog load."""
        # start the task
        self.update_rules.start()
        # pre-fill the autocomplete once
        await self.update_rules()

    def cog_unload(self) -> None:
        """Remove the autocomplete task on cog unload."""
        self.update_rules.cancel()

    async def _fetch_rules(self) -> Any:
        if isinstance(RUFF_RULES, pathlib.Path):
            with open(RUFF_RULES, "r") as f:
                return json.load(f)
        async with self.bot.http_session.get(RUFF_RULES) as response:
            if response.status == 200 and response.content_type == "application/json":
                return await response.json()
            return None

    @tasks.loop(hours=1)
    # @async_cached(cache=LRUMemoryCache(25, timeout=int(datetime.timedelta(hours=2).total_seconds())))
    async def update_rules(self) -> Optional[dict[str, Any]]:
        """Fetch Ruff rules."""
        raw_rules = await self._fetch_rules()
        new_rules = dict[str, Rule]()
        if not raw_rules:
            logger.error("Failed to fetch rules, something went wrong")
            return
        for unparsed_rule in raw_rules:
            parsed_rule = Rule(**unparsed_rule)
            new_rules[parsed_rule.code] = parsed_rule

        self.rules.clear()
        self.rules.update(new_rules)

        logger.info("Successfully loaded all ruff rules!")
        self.last_fetched = utcnow()

    @commands.slash_command(name="ruff")
    async def ruff(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Ruff."""
        pass

    @ruff.sub_command(name="rule")
    async def ruff_rules(self, inter: disnake.ApplicationCommandInteraction, rule: str) -> None:
        """
        Provide information about a specific rule from ruff.

        Parameters
        ----------
        rule: The rule to get information about
        """
        rule = rule.upper().strip()
        if rule not in self.rules:
            raise commands.BadArgument("'rule' must be a valid ruff rule. That rule does not exist.")

        ruleObj = self.rules[rule]
        embed = disnake.Embed(colour=disnake.Colour(next(RUFF_COLOUR_CYCLE)))

        embed.set_footer(
            text="ruleset last cached", icon_url="https://avatars.githubusercontent.com/u/115962839?s=200&v=4"
        )
        embed.set_author(
            name="ruff rules", icon_url="https://cdn.discordapp.com/emojis/1122704477334548560.webp?size=256"
        )
        embed.timestamp = self.last_fetched
        embed.title = ""
        if ruleObj.preview:
            embed.title = "🧪 "
        # else:
        # embed.title = "✔️ "
        embed.title += ruleObj.title
        embed.description = ruleObj.summary

        url = f"{RUFF_RULES_BASE_URL}/{ruleObj.name}/"
        # embed.description += f"\n\n*[View More]({url})*"
        embed.url = url

        if ruleObj.fix in {"Fix is sometimes available.", "Fix is always available."}:
            embed.add_field("Fixable status", ruleObj.fix)

        # check if rule has been deprecated
        if "deprecated" in ruleObj.explanation.split("/n")[0].lower():
            embed.add_field(
                "WARNING", "This rule may have been deprecated. Please check the docs for more information."
            )

        await inter.response.send_message(
            embed=embed,
            components=[
                DeleteButton(inter.author),
                disnake.ui.Button(label="View More", style=disnake.ButtonStyle.url, url=url),
            ],
        )

    @ruff_rules.autocomplete("rule")
    async def ruff_rule_autocomplete(self, inter: disnake.ApplicationCommandInteraction, option: str) -> dict[str, str]:
        """Provide autocomplete for ruff rules."""
        # return dict(sorted([[code, code] for code, rule in self.rules.items()])[:25])
        option = option.upper().strip()
        results = rapidfuzz.process.extract(
            (option,),  # must be a nested sequence because of the preprocessor
            self.rules.items(),
            scorer=rapidfuzz.fuzz.WRatio,
            limit=20,
            processor=lambda x: x[0],
            score_cutoff=0.6,
        )
        return {code[0][1].title: code[0][0] for code in results}


def setup(bot: Monty) -> None:
    """Load the Ruff cog."""
    bot.add_cog(Ruff(bot))
