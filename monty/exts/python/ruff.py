import asyncio
import itertools
import json
import random
import re
from functools import cache
from typing import TYPE_CHECKING, Any, Literal

import attrs
import disnake
import rapidfuzz.fuzz
import rapidfuzz.process
from disnake.ext import commands, tasks

from monty import constants
from monty.bot import Monty
from monty.log import get_logger
from monty.utils.converters import NOT_PYPI_PACKAGE_REGEX
from monty.utils.helpers import utcnow
from monty.utils.messages import DeleteButton


if TYPE_CHECKING:
    import datetime


logger = get_logger(__name__)


RUFF_RULES = "https://raw.githubusercontent.com/onerandomusername/ruff-rules/refs/heads/main/rules.json"
RUFF_LINTERS = "https://raw.githubusercontent.com/onerandomusername/ruff-rules/refs/heads/main/linters.json"

RUFF_RULES_BASE_URL = "https://docs.astral.sh/ruff/rules"

RUFF_COLOUR_CYCLE = itertools.cycle(disnake.Colour(c) for c in (0xD7FF66, 0x30173D))


@attrs.define(hash=True, frozen=True)
class Category:
    name: str
    prefix: str

    def get_fragment(self) -> str:
        """Return the fragment identifier for this category."""
        return f"{self.name} {self.prefix}".casefold().replace(" ", "-")

    def get_astral_url(self) -> str:
        """Return the URL to the linter documentation on docs.astral.sh."""
        return f"{RUFF_RULES_BASE_URL}/#{self.get_fragment()}"

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Rule from a dictionary."""
        return cls(**{a.name: data[a.name] for a in attrs.fields(cls)})


@attrs.define(hash=True, frozen=True)
class Linter:
    name: str
    prefix: str

    categories: tuple[Category] = attrs.field(converter=tuple[Category])

    @property
    def id(self) -> str:
        """Return the ID for this category."""
        return self.name

    def get_pypi_link(self) -> str | None:
        """Return the PyPI link for this category."""
        casefolded_name = self.name.casefold()
        if NOT_PYPI_PACKAGE_REGEX.search(casefolded_name):
            return None
        return f"https://pypi.org/project/{casefolded_name}/"

    @property
    def autocomplete(self) -> str:
        """Return autocomplete value."""
        return self.get_title()

    def _get_prefix(self, *, include_commas: bool) -> str:
        """Return the prefix for this category."""
        if self.prefix:
            return self.prefix

        return (", " if include_commas else " ").join(c.prefix for c in self.categories)

    def get_title(self) -> str:
        """Return a human-readable title."""
        return self.name + " (" + self._get_prefix(include_commas=True) + ")"

    def get_fragment(self) -> str:
        """Return the fragment identifier for this category."""
        return f"{self.name} {self._get_prefix(include_commas=False)}".casefold().replace(" ", "-")

    def get_astral_url(self) -> str:
        """Return the URL to the linter documentation on docs.astral.sh."""
        return f"{RUFF_RULES_BASE_URL}/#{self.get_fragment()}"

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Rule from a dictionary."""
        if "categories" not in data:
            data["categories"] = []
        else:
            data["categories"] = [Category.from_dict(d) for d in data["categories"]]
        return cls(**{a.name: data[a.name] for a in attrs.fields(cls)})


@attrs.define(hash=True, frozen=True)
class Rule:
    name: str
    code: str
    linter: str
    summary: str
    message_formats: tuple[str] = attrs.field(converter=tuple[str])
    fix: str
    explanation: str
    preview: bool
    status: dict[str, dict[str, str]] = attrs.field(hash=False)  # {"Stable": { "since": "v0.0.213"}}

    @property
    def title(self) -> str:
        """Return a human-readable title."""
        return self.name + " (" + self.code + ")"

    @property
    def autocomplete(self) -> str:
        """Return autocomplete value."""
        return self.code + ": " + self.name

    @property
    def id(self) -> str:
        """Return the ID for this rule."""
        return self.code

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

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Rule from a dictionary."""
        return cls(**{a.name: data[a.name] for a in attrs.fields(cls)})


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
        self.linters: dict[str, Linter] = {}

        self.last_fetched: datetime.datetime | None = None

    async def cog_load(self) -> None:
        """Load the rules on cog load."""
        # start the task
        self.update_ruff_cache.start()
        # pre-fill the autocomplete once
        await self.update_ruff_cache()

    def cog_unload(self) -> None:
        """Remove the autocomplete task on cog unload."""
        self.update_ruff_cache.cancel()

    async def _fetch_source(self, url: str) -> Any:
        async with self.bot.http_session.get(url) as response:
            if response.status == 200:
                return json.loads(await response.text())
            return None

    @tasks.loop(minutes=10)
    # @async_cached(cache=LRUMemoryCache(25, timeout=int(datetime.timedelta(hours=2).total_seconds())))
    async def update_ruff_cache(self) -> dict[str, Any] | None:
        """Fetch Ruff rules."""
        raw_rules = await self._fetch_source(RUFF_RULES)
        if not raw_rules:
            logger.error("Failed to fetch rules, something went wrong")
            self.last_fetched = utcnow()  # don't try again for an hour
            return

        new_rules = dict[str, Rule]()
        for unparsed_rule in raw_rules:
            parsed_rule = Rule.from_dict(unparsed_rule)
            new_rules[parsed_rule.code] = parsed_rule

        raw_linters = await self._fetch_source(RUFF_LINTERS)
        if not raw_linters:
            logger.error("Failed to fetch linters, something went wrong")
            self.last_fetched = utcnow()  # don't try again for an hour
            return

        new_linters = dict[str, Linter]()
        for unparsed_linter in raw_linters:
            parsed_linter = Linter.from_dict(unparsed_linter)
            new_linters[parsed_linter.name.casefold()] = parsed_linter

        self.rules.clear()
        self.rules.update(new_rules)
        self.linters.clear()
        self.linters.update(new_linters)

        logger.info("Successfully loaded all ruff rules!")
        self.last_fetched = utcnow()

    @commands.slash_command(name="ruff")
    async def ruff(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Ruff."""

    @ruff.sub_command(name="linter")
    async def ruff_linter(self, inter: disnake.ApplicationCommandInteraction, linter: str) -> None:
        """
        Provide information about a specific linter from ruff.

        Parameters
        ----------
        linter: The linter to get information about
        """
        normalised_linter = linter.lower().strip()
        linter_obj = self.linters.get(normalised_linter)
        if linter and not linter_obj:
            # try to get with the prefix
            for linter_candidate in self.linters.values():
                if linter_candidate.prefix.lower() == normalised_linter:
                    linter_obj = linter_candidate
                    break
                if linter_candidate.categories:
                    for category in linter_candidate.categories:
                        if category.prefix.lower() == normalised_linter:
                            linter_obj = linter_candidate
                            break
                    if linter_obj:
                        break
        if not linter_obj:
            msg = f"'linter' must be a valid ruff linter. The linter {linter} does not exist."
            raise commands.BadArgument(msg)

        container = disnake.ui.Container(
            disnake.ui.TextDisplay(f"-# ruff » linters » {linter_obj.get_title()}"),
            accent_colour=next(RUFF_COLOUR_CYCLE),
        )

        url = linter_obj.get_astral_url()

        description = f"## [{linter_obj.get_title()}]({url})\n"

        if pypi_link := linter_obj.get_pypi_link():
            description += f"For more, see [{linter_obj.name}]({pypi_link}) on PyPI.\n"

        supported_rules = {x for x in self.rules.values() if x.linter.casefold() == normalised_linter}

        description += "### Rule counts\n"
        description += f"Stable: {len(supported_rules)}\n"
        if preview_rules := [r for r in supported_rules if r.preview]:
            description += f"Preview: {len(preview_rules)}\n"
        if removed_rules := [r for r in supported_rules if r.status.get("Removed")]:
            description += f"Removed: {len(removed_rules)}\n"

        if linter_obj.categories:
            description += "### Categories\n"
            for category in linter_obj.categories:
                description += f"- {category.name} ({category.prefix})\n"
        if not description:
            msg = "No description could be generated for this linter."
            raise commands.CommandError(msg)

        container.children.append(disnake.ui.TextDisplay(description))

        components = [
            container,
            disnake.ui.ActionRow(
                DeleteButton(inter.author),
                disnake.ui.Button(
                    label="See on docs.astral.sh",
                    style=disnake.ButtonStyle.url,
                    url=linter_obj.get_astral_url(),
                    emoji=disnake.PartialEmoji(name="bolt", id=1122704443117424722),
                ),
            ),
        ]

        await inter.response.send_message(components=components)

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
            disnake.ui.TextDisplay(f"-# ruff » rules » {rule_obj.name}"),
            accent_colour=next(RUFF_COLOUR_CYCLE),
        )
        description = f"## [{rule_obj.title}]({rule_obj.url})\n"
        if (
            rule_obj.linter
            and (linter := self.linters.get(rule_obj.linter.casefold()))
            and (pypi_link := linter.get_pypi_link())
        ):
            description += f"Derived from the [{rule_obj.linter}]({pypi_link}) linter.\n"
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

    async def ruff_autocomplete(
        self, inter: disnake.ApplicationCommandInteraction, option: str, *, attr_list: Literal["rule", "linter"]
    ) -> dict[str, str]:
        """Provide autocomplete for ruff rules."""
        # return dict(sorted([[code, code] for code, rule in self.rules.items()])[:25])
        if attr_list == "rule":
            rules_dict = self.rules
            option = option.upper().strip()
        elif attr_list == "linter":
            rules_dict = self.linters
            option = option.lower().strip()
        else:
            return {}

        if not rules_dict:
            return {}

        if not option:
            return {rule.autocomplete: rule.id for rule in random.choices(list(rules_dict.values()), k=12)}

        class Fake:
            autocomplete = option.upper() if attr_list == "linter" else option.lower()

        # score twice, once on name, and once on the full name with the code
        results = rapidfuzz.process.extract(
            (option, Fake),  # must be a nested sequence because of the preprocessor
            rules_dict.items(),
            scorer=rapidfuzz.fuzz.WRatio,
            limit=20,
            processor=lambda x: x[0],
            score_cutoff=0.6,
        )
        results2 = rapidfuzz.process.extract(
            (option, Fake),  # must be a nested sequence because of the preprocessor
            rules_dict.items(),
            scorer=rapidfuzz.fuzz.WRatio,
            limit=20,
            processor=lambda x: x[1].autocomplete,
            score_cutoff=0.6,
        )

        # get the best matches from both
        matches: dict[str, str] = {}
        for _ in range(20):
            if results and results[0][1] > results2[0][1]:
                code, rule = results.pop(0)[0]
            elif results2:
                code, rule = results2.pop(0)[0]
            else:
                break
            matches[rule.autocomplete] = code

        return matches

    @ruff_rules.autocomplete("rule")
    async def ruff_rule_autocomplete(self, inter: disnake.ApplicationCommandInteraction, option: str) -> dict[str, str]:
        """Provide autocomplete for ruff rules."""
        return await self.ruff_autocomplete(inter, option, attr_list="rule")

    @ruff_linter.autocomplete("linter")
    async def ruff_linter_autocomplete(
        self, inter: disnake.ApplicationCommandInteraction, option: str
    ) -> dict[str, str]:
        """Provide autocomplete for ruff rules."""
        return await self.ruff_autocomplete(inter, option, attr_list="linter")

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
