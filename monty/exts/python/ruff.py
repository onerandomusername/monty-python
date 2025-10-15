import asyncio
import itertools
import json
import random
import re
from functools import cache
from typing import TYPE_CHECKING, Any

import attrs
import disnake
import rapidfuzz.fuzz
import rapidfuzz.process
from disnake.ext import commands, tasks

from monty import constants
from monty.bot import Monty
from monty.log import get_logger
from monty.utils.helpers import utcnow
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    import datetime


logger = get_logger(__name__)


RUFF_RULES = "https://raw.githubusercontent.com/onerandomusername/ruff-rules/refs/heads/main/rules.json"

RUFF_RULES_BASE_URL = "https://docs.astral.sh/ruff/rules"

RUFF_COLOUR_CYCLE = itertools.cycle(disnake.Colour(c) for c in (0xD7FF66, 0x30173D))


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
        return self.name + " (" + self.code + ")"

    @property
    def code_with_name(self) -> str:
        """Return code with name."""
        return self.code + ": " + self.name

    @property
    def short_description(self) -> str:
        """Return a description."""
        linter_text = "" if "ruff" in self.linter else f"Derived from the {self.linter} linter.\n"
        fix_text = self.fix + "\n" if self.fix != "Fix is not available." else ""
        preview_text = (
            "This rule is unstable and in preview. The --preview flag is required for use.\n" if self.preview else ""
        )

        return linter_text + fix_text + preview_text

    @property
    def url(self) -> str:
        """Return the URL to the rule documentation."""
        return f"{RUFF_RULES_BASE_URL}/{self.name}/"

    @cache  # noqa: B019
    def all_sections(self) -> list[tuple[str, str]]:
        """
        Return all markdown sections while normalizing codeblock spacing and converting reference links.

        Returns
        -------
        list[tuple[str, str]]
            A list of tuples containing section names and their corresponding content.
        """
        sections: list[tuple[str, str]] = []
        text = self.explanation

        # support markdown shorthand when they're defined
        # Find all [name]: link references in the entire content
        ref_pattern = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)
        refs = dict(ref_pattern.findall(text))
        # Remove reference lines from content
        text = ref_pattern.sub("", text)
        # Replace all [xyz] with [xyz](link) throughout the content
        for label, url in refs.items():
            text = re.sub(rf"\[{re.escape(label)}\]", f"[{label}]({url})", text)

        pattern = re.compile(r"^## (.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        for i, match in enumerate(matches):
            name = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            # Normalize codeblock endings: ensure only one newline after each codeblock
            content = re.sub(r"(```[\w]*\n[\s\S]*?```)(\n{2,})", r"\1\n", content)
            # Normalize quotes: ensure that >> lines have whitespace
            content = re.sub(r"^(>+)\s*$", r"\1 ", content, flags=re.MULTILINE)
            sections.append((name, content))
        return sections


class Ruff(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Cog for getting information about Ruff and other rules."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.fetch_lock = asyncio.Lock()

        self.rules: dict[str, Rule] = {}

        self.last_fetched: datetime.datetime | None = None

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
        async with self.bot.http_session.get(RUFF_RULES) as response:
            if response.status == 200:
                return json.loads(await response.text())
            return None

    @tasks.loop(minutes=10)
    # @async_cached(cache=LRUMemoryCache(25, timeout=int(datetime.timedelta(hours=2).total_seconds())))
    async def update_rules(self) -> dict[str, Any] | None:
        """Fetch Ruff rules."""
        raw_rules = await self._fetch_rules()
        if not raw_rules:
            logger.error("Failed to fetch rules, something went wrong")
            self.last_fetched = utcnow()  # don't try again for an hour
            return

        new_rules = dict[str, Rule]()
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

    @ruff.sub_command(name="rule")
    async def ruff_rules(self, inter: disnake.ApplicationCommandInteraction, rule: str) -> None:
        """
        Provide information about a specific rule from ruff.

        Parameters
        ----------
        rule: The rule to get information about
        """
        normalised_rule = rule.upper().strip()
        if normalised_rule not in self.rules:
            msg = f"'rule' must be a valid ruff rule. The rule {rule} does not exist."
            raise commands.BadArgument(msg)
        rule = normalised_rule
        del normalised_rule

        rule_obj = self.rules[rule]
        if not await self.bot.guild_has_feature(inter.guild_id, constants.Feature.RUFF_RULE_V2):
            await self._legacy_embed(inter, rule_obj)
            return

        # Build components v2 layout
        container = disnake.ui.Container(
            disnake.ui.TextDisplay(f"-# ruff » rules » {rule_obj.code}"),
            accent_colour=next(RUFF_COLOUR_CYCLE),
        )
        description = f"## [{rule_obj.title}]({rule_obj.url})\n"
        if rule_obj.linter != "ruff":
            description += f"Derived from the {rule_obj.linter} linter.\n"
        if rule_obj.fix != "Fix is not available.":
            description += f"{rule_obj.fix}\n"

        if description:
            container.children.append(disnake.ui.TextDisplay(description))

        for name, section in rule_obj.all_sections():
            container.children.append(disnake.ui.TextDisplay(f"### {name}\n{section}"))

        # Add Delete and View More buttons
        action_row = disnake.ui.ActionRow(
            DeleteButton(inter.author),
            disnake.ui.Button(
                label="See on docs.astral.sh",
                style=disnake.ButtonStyle.url,
                url=rule_obj.url,
                emoji=disnake.PartialEmoji(name="bolt", id=1122704443117424722),
            ),
        )

        await inter.response.send_message(
            components=[container, action_row],
        )

    async def _legacy_embed(self, inter: disnake.ApplicationCommandInteraction, rule_obj: Rule) -> None:
        """Create an embed for a rule."""
        embed = disnake.Embed(colour=next(RUFF_COLOUR_CYCLE))

        embed.set_footer(
            text=f"original linter: {rule_obj.linter}",
            icon_url="https://avatars.githubusercontent.com/u/115962839?s=200&v=4",
        )
        embed.set_author(
            name="ruff rules", icon_url="https://cdn.discordapp.com/emojis/1122704477334548560.webp?size=256"
        )
        # embed.timestamp = self.last_fetched
        embed.title = ""
        if rule_obj.preview:
            embed.title = "🧪 "
        embed.title += rule_obj.title

        try:
            embed.description = rule_obj.explanation.split("## What it does\n", 1)[-1].split("## Why is this bad?")[0]
        except Exception as err:
            logger.error("Something went wrong trying to get the summary from the description", exc_info=err)

        url = f"{RUFF_RULES_BASE_URL}/{rule_obj.name}/"
        embed.url = url

        if rule_obj.fix in {"Fix is sometimes available.", "Fix is always available."}:
            embed.add_field(
                "Fixable status",
                rule_obj.fix,
                inline=False,
            )

        # check if rule has been deprecated
        if "deprecated" in rule_obj.explanation.split("/n")[0].lower():
            embed.add_field(
                "WARNING",
                "This rule may have been deprecated. Please check the docs for more information.",
                inline=False,
            )

        if rule_obj.preview:
            embed.add_field(
                "Preview",
                "This rule is still in preview, and may be subject to change.",
                inline=False,
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
        if not self.rules:
            return {}

        option = option.upper().strip()
        if not option:
            return {rule.code_with_name: rule.code for rule in random.choices(list(self.rules.values()), k=12)}

        class Fake:
            code_with_name = option

        # score twice, once on name, and once on the full name with the code
        results = rapidfuzz.process.extract(
            (option, Fake),  # must be a nested sequence because of the preprocessor
            self.rules.items(),
            scorer=rapidfuzz.fuzz.WRatio,
            limit=20,
            processor=lambda x: x[0],
            score_cutoff=0.6,
        )
        results2 = rapidfuzz.process.extract(
            (option, Fake),  # must be a nested sequence because of the preprocessor
            self.rules.items(),
            scorer=rapidfuzz.fuzz.WRatio,
            limit=20,
            processor=lambda x: x[1].code_with_name,
            score_cutoff=0.6,
        )

        # get the best matches from both
        matches: dict[str, str] = {}
        for _ in range(20):
            if results[0][1] > results2[0][1]:
                code, rule = results.pop(0)[0]
            else:
                code, rule = results2.pop(0)[0]
            matches[rule.code_with_name] = code

        return matches

    def check_ruff_rules_loaded(self, inter: disnake.ApplicationCommandInteraction) -> bool:
        """A check for all commands in this cog."""
        if not self.rules:
            msg = "Ruff rules have not been loaded yet, please try again later."
            raise commands.CommandError(msg)
        return True

    def cog_slash_command_check(self, inter: disnake.ApplicationCommandInteraction) -> bool:
        """A check for all commands in this cog."""
        if inter.application_command.qualified_name.startswith("ruff rule"):
            return self.check_ruff_rules_loaded(inter)

        return True


def setup(bot: Monty) -> None:
    """Load the Ruff cog."""
    bot.add_cog(Ruff(bot))
