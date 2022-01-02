from __future__ import annotations

import asyncio
import copy
import functools
import sys
import textwrap
from collections import defaultdict
from types import SimpleNamespace
from typing import Dict, Literal, NamedTuple, Optional, Tuple, TypedDict, Union

import aiohttp
import disnake
from disnake.ext import commands

from bot import constants
from bot.bot import Bot
from bot.constants import RedirectOutput
from bot.converters import Inventory, PackageName, ValidURL
from bot.log import get_logger
from bot.utils import scheduling
from bot.utils.delete import get_view
from bot.utils.lock import SharedEvent, lock
from bot.utils.pagination import LinePaginator
from bot.utils.scheduling import Scheduler

from . import NAMESPACE, PRIORITY_PACKAGES, _batch_parser, doc_cache
from ._inventory_parser import InvalidHeaderError, InventoryDict, fetch_inventory


log = get_logger(__name__)

# symbols with a group contained here will get the group prefixed on duplicates
FORCE_PREFIX_GROUPS = (
    "term",
    "label",
    "token",
    "doc",
    "pdbcommand",
    "2to3fixer",
)
NOT_FOUND_DELETE_DELAY = RedirectOutput.delete_delay
# Delay to wait before trying to reach a rescheduled inventory again, in minutes
FETCH_RESCHEDULE_DELAY = SimpleNamespace(first=2, repeated=5)

COMMAND_LOCK_SINGLETON = "inventory refresh"

CONFIG_DOC_PREFIX = "global.documentation.inventories"


class DocDict(TypedDict):
    """Documentation source attributes."""

    package: str
    base_url: str
    inventory_url: str


BLACKLIST: dict[int, set[str]] = {}
BLACKLIST_MAPPING: dict[int, list[str]] = {
    constants.Guilds.disnake: ["nextcord"],
    constants.Guilds.nextcord: ["disnake"],
}


class DocItem(NamedTuple):
    """Holds inventory symbol information."""

    package: str  # Name of the package name the symbol is from
    group: str  # Interpshinx "role" of the symbol, for example `label` or `method`
    base_url: str  # Absolute path to to which the relative path resolves, same for all items with the same package
    relative_url_path: str  # Relative path to the page where the symbol is located
    symbol_id: str  # Fragment id used to locate the symbol on the page

    @property
    def url(self) -> str:
        """Return the absolute url to the symbol."""
        return self.base_url + self.relative_url_path


def defaultdict_factory() -> defaultdict:
    """Factory method for defaultdicts."""
    return defaultdict(defaultdict_factory)


class DocCog(commands.Cog):
    """A set of commands for querying & displaying documentation."""

    def __init__(self, bot: Bot):
        # Contains URLs to documentation home pages.
        # Used to calculate inventory diffs on refreshes and to display all currently stored inventories.
        self.base_urls = {}
        self.bot = bot
        self.doc_symbols: Dict[str, DocItem] = {}  # Maps symbol names to objects containing their metadata.
        self.autocomplete_symbols: defaultdict[Union[dict, str]] = defaultdict_factory()
        self.item_fetcher = _batch_parser.BatchParser()
        # Maps a conflicting symbol name to a list of the new, disambiguated names created from conflicts with the name.
        self.renamed_symbols = defaultdict(list)

        self.inventory_scheduler = Scheduler(self.__class__.__name__)

        self.refresh_event = asyncio.Event()
        self.refresh_event.set()
        self.symbol_get_event = SharedEvent()

        self.init_refresh_task = scheduling.create_task(
            self.init_refresh_inventory(),
            name="Doc inventory init",
            event_loop=self.bot.loop,
        )

    def _get_default_completion(
        self,
        inter: disnake.ApplicationCommandInteraction,
        guild: disnake.Guild = None,
    ) -> list[str]:
        if guild:
            if guild.id == constants.Guilds.disnake:
                return ["disnake", "disnake.ext.commands", "disnake.ext.tasks"]
            elif guild.id == constants.Guilds.nextcord:
                return ["nextcord", "nextcord.ext.commands", "nextcord.ext.tasks"]

        return [
            "__future__",
            "asyncio",
            "dataclasses",
            "datetime",
            "enum",
            "html",
            "http",
            "importlib",
            "inspect",
            "json",
            "logging",
            "os",
            "pathlib",
            "textwrap",
            "time",
            "traceback",
            "typing",
            "unittest",
            "warnings",
            "zipfile",
            "zipimport",
        ]

    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    async def init_refresh_inventory(self) -> None:
        """Refresh documentation inventory on cog initialization."""
        # await self.bot.wait_until_guild_available()
        await self.refresh_inventories()

    def update_single(
        self,
        package_name: str,
        base_url: str,
        inventory: InventoryDict,
        blacklist_guilds: list[int] = None,
    ) -> None:
        """
        Build the inventory for a single package.

        Where:
            * `package_name` is the package name to use in logs and when qualifying symbols
            * `base_url` is the root documentation URL for the specified package, used to build
                absolute paths that link to specific symbols
            * `package` is the content of a intersphinx inventory.
        """
        self.base_urls[package_name] = base_url

        for group, items in inventory.items():
            for symbol_name, relative_doc_url in items:

                # e.g. get 'class' from 'py:class'
                group_name = group.split(":")[1]
                symbol_name = self.ensure_unique_symbol_name(
                    package_name,
                    group_name,
                    symbol_name,
                )

                relative_url_path, _, symbol_id = relative_doc_url.partition("#")
                # Intern fields that have shared content so we're not storing unique strings for every object
                doc_item = DocItem(
                    package_name,
                    sys.intern(group_name),
                    base_url,
                    sys.intern(relative_url_path),
                    symbol_id,
                )
                self.doc_symbols[symbol_name] = doc_item
                if blacklist_guilds:
                    for guild_id in blacklist_guilds:
                        if BLACKLIST.get(guild_id) is None:
                            BLACKLIST[guild_id] = set()
                        BLACKLIST[guild_id].add(symbol_name)

                self.item_fetcher.add_item(doc_item)

        log.trace(f"Fetched inventory for {package_name}.")

    async def update_or_reschedule_inventory(
        self,
        api_package_name: str,
        base_url: str,
        inventory_url: str,
    ) -> None:
        """
        Update the cog's inventories, or reschedule this method to execute again if the remote inventory is unreachable.

        The first attempt is rescheduled to execute in `FETCH_RESCHEDULE_DELAY.first` minutes, the subsequent attempts
        in `FETCH_RESCHEDULE_DELAY.repeated` minutes.
        """
        try:
            package = await fetch_inventory(inventory_url)
        except InvalidHeaderError as e:
            # Do not reschedule if the header is invalid, as the request went through but the contents are invalid.
            log.warning(f"Invalid inventory header at {inventory_url}. Reason: {e}")
            return

        if not package:
            if api_package_name in self.inventory_scheduler:
                self.inventory_scheduler.cancel(api_package_name)
                delay = FETCH_RESCHEDULE_DELAY.repeated
            else:
                delay = FETCH_RESCHEDULE_DELAY.first
            log.info(f"Failed to fetch inventory; attempting again in {delay} minutes.")
            self.inventory_scheduler.schedule_later(
                delay * 60,
                api_package_name,
                self.update_or_reschedule_inventory(api_package_name, base_url, inventory_url),
            )
        else:
            if not base_url:
                base_url = self.base_url_from_inventory_url(inventory_url)
            # determine blacklist
            blacklist_guilds = []
            for g, packs in BLACKLIST_MAPPING.items():
                if api_package_name in packs:
                    blacklist_guilds.append(g)

            if blacklist_guilds:
                print(blacklist_guilds)

            self.update_single(api_package_name, base_url, package, blacklist_guilds)

    def ensure_unique_symbol_name(self, package_name: str, group_name: str, symbol_name: str) -> str:
        """
        Ensure `symbol_name` doesn't overwrite an another symbol in `doc_symbols`.

        For conflicts, rename either the current symbol or the existing symbol with which it conflicts.
        Store the new name in `renamed_symbols` and return the name to use for the symbol.

        If the existing symbol was renamed or there was no conflict, the returned name is equivalent to `symbol_name`.
        """
        if (item := self.doc_symbols.get(symbol_name)) is None:
            return symbol_name  # There's no conflict so it's fine to simply use the given symbol name.

        def rename(prefix: str, *, rename_extant: bool = False) -> str:
            new_name = f"{prefix}.{symbol_name}"
            if new_name in self.doc_symbols:
                # If there's still a conflict, qualify the name further.
                if rename_extant:
                    new_name = f"{item.package}.{item.group}.{symbol_name}"
                else:
                    new_name = f"{package_name}.{group_name}.{symbol_name}"

            self.renamed_symbols[symbol_name].append(new_name)

            if rename_extant:
                # Instead of renaming the current symbol, rename the symbol with which it conflicts.
                self.doc_symbols[new_name] = self.doc_symbols[symbol_name]
                return symbol_name
            else:
                return new_name

        # When there's a conflict, and the package names of the items differ, use the package name as a prefix.
        if package_name != item.package:
            if package_name in PRIORITY_PACKAGES:
                return rename(item.package, rename_extant=True)
            else:
                return rename(package_name)

        # If the symbol's group is a non-priority group from FORCE_PREFIX_GROUPS,
        # add it as a prefix to disambiguate the symbols.
        elif group_name in FORCE_PREFIX_GROUPS:
            if item.group in FORCE_PREFIX_GROUPS:
                needs_moving = FORCE_PREFIX_GROUPS.index(group_name) < FORCE_PREFIX_GROUPS.index(item.group)
            else:
                needs_moving = False
            return rename(item.group if needs_moving else group_name, rename_extant=needs_moving)

        # If the above conditions didn't pass, either the existing symbol has its group in FORCE_PREFIX_GROUPS,
        # or deciding which item to rename would be arbitrary, so we rename the existing symbol.
        else:
            return rename(item.group, rename_extant=True)

    async def refresh_inventories(self) -> None:
        """Refresh internal documentation inventories."""
        self.refresh_event.clear()
        await self.symbol_get_event.wait()
        log.debug("Refreshing documentation inventory...")
        self.inventory_scheduler.cancel_all()

        self.base_urls.clear()
        self.doc_symbols.clear()
        self.renamed_symbols.clear()
        await self.item_fetcher.clear()

        async def get_packages() -> list[dict[str, str]]:
            _, res = await self.bot.db.list_keys(CONFIG_DOC_PREFIX + ".")
            res = [x["name"] for x in res["result"]["keys"]]
            _, kv = await self.bot.db.fetch_keys(*res)
            kv: dict[str, str] = kv["config"]
            packages = {}
            for pack, value in kv.items():
                pack = pack[len(CONFIG_DOC_PREFIX) + 1 :]
                if len(spl := pack.split(".", 1)) > 1:
                    packages.setdefault(spl[0], {})[spl[1]] = value
                else:
                    packages.setdefault(spl[0], {})["package"] = spl[0]

            return packages.values()

        coros = [
            self.update_or_reschedule_inventory(package["package"], package["base_url"], package["inventory_url"])
            for package in await get_packages()
        ]
        await asyncio.gather(*coros)
        log.debug("Finished inventory refresh.")
        self.refresh_event.set()

    def get_symbol_item(self, symbol_name: str) -> Tuple[str, Optional[DocItem]]:
        """
        Get the `DocItem` and the symbol name used to fetch it from the `doc_symbols` dict.

        If the doc item is not found directly from the passed in name and the name contains a space,
        the first word of the name will be attempted to be used to get the item.
        """
        doc_item = self.doc_symbols.get(symbol_name)
        if doc_item is None and " " in symbol_name:
            symbol_name = symbol_name.split(" ", maxsplit=1)[0]
            doc_item = self.doc_symbols.get(symbol_name)

        return symbol_name, doc_item

    async def get_symbol_markdown(
        self, doc_item: DocItem, inter: Optional[disnake.ApplicationCommandInteraction] = None
    ) -> str:
        """
        Get the Markdown from the symbol `doc_item` refers to.

        First a redis lookup is attempted, if that fails the `item_fetcher`
        is used to fetch the page and parse the HTML from it into Markdown.
        """
        markdown = await doc_cache.get(doc_item)

        if markdown is None:
            if inter:
                log.debug("Deferring interaction since contents are not cached.")
                await inter.response.defer()
            log.debug(f"Redis cache miss with {doc_item}.")
            try:
                markdown = await self.item_fetcher.get_markdown(doc_item)

            except aiohttp.ClientError as e:
                log.warning(f"A network error has occurred when requesting parsing of {doc_item}.", exc_info=e)
                return "Unable to parse the requested symbol due to a network error."

            except Exception:
                log.exception(f"An unexpected error has occurred when requesting parsing of {doc_item}.")
                return "Unable to parse the requested symbol due to an error."

            if markdown is None:
                return "Unable to parse the requested symbol."
        return markdown

    async def create_symbol_embed(
        self,
        symbol_name: str,
        inter: Optional[disnake.ApplicationCommandInteraction] = None,
    ) -> Optional[disnake.Embed]:
        """
        Attempt to scrape and fetch the data for the given `symbol_name`, and build an embed from its contents.

        If the symbol is known, an Embed with documentation about it is returned.

        First check the DocRedisCache before querying the cog's `BatchParser`.
        """
        log.trace(f"Building embed for symbol `{symbol_name}`")
        if not self.refresh_event.is_set():
            log.debug("Waiting for inventories to be refreshed before processing item.")
            await self.refresh_event.wait()
        # Ensure a refresh can't run in case of a context switch until the with block is exited
        with self.symbol_get_event:
            symbol_name, doc_item = self.get_symbol_item(symbol_name)
            if doc_item is None:
                log.debug("Symbol does not exist.")
                return None

            # Show all symbols with the same name that were renamed in the footer,
            # with a max of 200 chars.
            if symbol_name in self.renamed_symbols:
                renamed_symbols = ", ".join(self.renamed_symbols[symbol_name])
                footer_text = textwrap.shorten("Similar names: " + renamed_symbols, 200, placeholder=" ...")
            else:
                footer_text = ""

            embed = disnake.Embed(
                title=disnake.utils.escape_markdown(symbol_name),
                url=f"{doc_item.url}#{doc_item.symbol_id}",
                description=await self.get_symbol_markdown(doc_item, inter=inter),
            )
            embed.set_footer(text=footer_text)
            return embed

    @commands.group(name="docs", aliases=("doc", "d"), invoke_without_command=True)
    async def docs_group(self, ctx: commands.Context, *, search: Optional[str]) -> None:
        """Look up documentation for Python symbols."""
        await self.docs_get_command(ctx, search=search)

    @commands.slash_command(name="docs")
    async def slash_docs(self, inter: disnake.AppCmdInter) -> None:
        """Search python package documentation."""
        pass

    @slash_docs.sub_command("item")
    async def docs_get_command(self, inter: disnake.ApplicationCommandInteraction, search: Optional[str]) -> None:
        """
        Gives you a documentation link for a provided entry.

        Parameters
        ----------
        search: the object to view the docs
        """
        if not search:
            inventory_embed = disnake.Embed(
                title=f"All inventories (`{len(self.base_urls)}` total)", colour=disnake.Colour.blue()
            )

            lines = sorted(f"• [`{name}`]({url})" for name, url in self.base_urls.items())
            if self.base_urls:
                await LinePaginator.paginate(lines, inter, inventory_embed, max_size=400, empty=False)

            else:
                inventory_embed.description = "Hmmm, seems like there's nothing here yet."
                await inter.send(embed=inventory_embed)

        else:
            symbol = search.strip("`")
            if isinstance(inter, disnake.Interaction):
                doc_embed = await self.create_symbol_embed(symbol, inter)
            else:
                doc_embed = await self.create_symbol_embed(symbol)

            if doc_embed is None:
                if isinstance(inter, disnake.ApplicationCommandInteraction):
                    await inter.send(f"No documentation found for `{search}`.", ephemeral=True)
                else:
                    await inter.send(f"No documentation found for `{search}`.")

            else:
                await inter.send(embed=doc_embed, view=get_view(inter))

    async def _docs_autocomplete(
        self,
        inter: disnake.Interaction,
        query: str,
        *,
        _recurse: bool = True,
        _levels: int = 0,
        return_query: bool = False,
    ) -> list[str]:
        """Autocomplete for the search param for documentation."""
        log.info(f"Received autocomplete inter by {inter.author}: {query}")
        max_completion = 20

        compare_len = len(query.rstrip("."))
        completion = set()

        blacklist = BLACKLIST.get(inter.guild_id)
        if not query:
            return self._get_default_completion(inter, inter.guild)

        for item in self.doc_symbols:
            if not item.startswith(query):
                continue

            # only keep items that aren't instantly delimited
            if item[compare_len:].count(".") >= 2 + _levels:
                continue

            # apply blacklist
            if blacklist and item in blacklist:
                continue

            completion.add(item)
            if len(completion) >= max_completion:
                break

        if _recurse and len(completion) < 2:
            # run the entire completion again
            completion.update(
                set(await self._docs_autocomplete(inter, query=query, _levels=_levels + 1, _recurse=False))
            )

        completion = list(sorted(completion))
        # log.debug('Options: ' + str(completion))
        if return_query:
            completion.insert(0, query)
            completion = completion[:max_completion]
        return completion

    docs_get_command.autocomplete("search")(copy.copy(_docs_autocomplete))

    @slash_docs.sub_command(name="list")
    async def slash_docs_search(self, inter: disnake.AppCmdInter, query: str) -> None:
        """
        [BETA] Search documentation and provide a list of results.

        Parameters
        ----------
        query: search query
        """
        compare_len = len(query.rstrip("."))
        results = {}
        for key, item in self.doc_symbols.items():
            if not key.startswith(query):
                continue

            # only keep items that aren't instantly delimited
            if key[compare_len:].count(".") >= 2:
                continue

            results[key] = item.url
            if len(results) >= 10:
                break
        # if no results
        if not results:
            await inter.response.send_message(f"No documentation results found for `{query}`.", ephemeral=True)
        # construct embed
        results = {key: val for key, val in sorted(results.items(), key=lambda x: x[0])}

        embed = disnake.Embed(title=f"Results for {query}")
        embed.description = ""
        for res, url in results.items():
            embed.description += f"[`{res}`]({url})\n"
        await inter.response.send_message(embed=embed, view=get_view(inter))

    slash_docs_search.autocomplete("query")(functools.partial(_docs_autocomplete, return_query=True))

    @staticmethod
    def base_url_from_inventory_url(inventory_url: str) -> str:
        """Get a base url from the url to an objects inventory by removing the last path segment."""
        return inventory_url.removesuffix("/").rsplit("/", maxsplit=1)[0] + "/"

    @docs_group.command(name="setdoc", aliases=("s",))
    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    @commands.is_owner()
    async def set_command(
        self,
        ctx: commands.Context,
        package_name: PackageName,
        inventory: Inventory,
        base_url: ValidURL = "",
    ) -> None:
        """
        Adds a new documentation metadata object to the site's database.

        The database will update the object, should an existing item with the specified `package_name` already exist.
        If the base url is not specified, a default created by removing the last segment of the inventory url is used.

        Example:
            !docs setdoc \
                    python \
                    https://docs.python.org/3/objects.inv
        """
        if base_url and not base_url.endswith("/"):
            raise commands.BadArgument("The base url must end with a slash.")
        inventory_url, inventory_dict = inventory
        prefix = f"{CONFIG_DOC_PREFIX}.{package_name}"
        _, resp = await self.bot.db.fetch_keys(prefix)
        if resp["config"].values():
            await ctx.send(":x: That package is already added!")
            return
        body = {
            prefix: package_name,
            f"{prefix}.base_url": str(base_url),
            f"{prefix}.inventory_url": str(inventory_url),
        }
        await self.bot.db.put_keys(**body)

        log.info(
            f"User @{ctx.author} ({ctx.author.id}) added a new documentation package:\n"
            + "\n".join(f"{key}: {value}" for key, value in body.items())
        )

        if not base_url:
            base_url = self.base_url_from_inventory_url(inventory_url)
        self.update_single(package_name, base_url, inventory_dict)
        await ctx.send(f"Added the package `{package_name}` to the database and updated the inventories.")

    @docs_group.command(name="deletedoc", aliases=("removedoc", "rm", "d"))
    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    @commands.is_owner()
    async def delete_command(self, ctx: commands.Context, package_name: PackageName) -> None:
        """
        Removes the specified package from the database.

        Example:
            !docs deletedoc aiohttp
        """
        status, resp = await self.bot.db.fetch_keys(f"{CONFIG_DOC_PREFIX}.{package_name}")
        keys = resp["config"].values()

        if not keys:
            await ctx.send(":x: No package found with that name.")
            return

        keys = {
            f"{CONFIG_DOC_PREFIX}.{package_name}",
            f"{CONFIG_DOC_PREFIX}.{package_name}.base_url",
            f"{CONFIG_DOC_PREFIX}.{package_name}.inventory_url",
        }
        await self.bot.db.delete_keys(*keys)

        async with ctx.typing():
            await self.refresh_inventories()
            await doc_cache.delete(package_name)
        await ctx.send(f"Successfully deleted `{package_name}` and refreshed the inventories.")

    @docs_group.command(name="refreshdoc", aliases=("rfsh", "r"))
    @commands.is_owner()
    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    async def refresh_command(self, ctx: commands.Context) -> None:
        """Refresh inventories and show the difference."""
        old_inventories = set(self.base_urls)
        with ctx.typing():
            await self.refresh_inventories()
        new_inventories = set(self.base_urls)

        if added := ", ".join(new_inventories - old_inventories):
            added = "+ " + added

        if removed := ", ".join(old_inventories - new_inventories):
            removed = "- " + removed

        embed = disnake.Embed(
            title="Inventories refreshed", description=f"```diff\n{added}\n{removed}```" if added or removed else ""
        )
        await ctx.send(embed=embed)

    @docs_group.command(name="cleardoccache", aliases=("deletedoccache",))
    @commands.is_owner()
    async def clear_cache_command(
        self, ctx: commands.Context, package_name: Union[PackageName, Literal["*"]]  # noqa: F722
    ) -> None:
        """Clear the persistent redis cache for `package`."""
        if await doc_cache.delete(package_name):
            await self.item_fetcher.stale_inventory_notifier.symbol_counter.delete(package_name)
            await ctx.send(f"Successfully cleared the cache for `{package_name}`.")
        else:
            await ctx.send("No keys matching the package found.")

    def cog_unload(self) -> None:
        """Clear scheduled inventories, queued symbols and cleanup task on cog unload."""
        self.inventory_scheduler.cancel_all()
        self.init_refresh_task.cancel()
        scheduling.create_task(self.item_fetcher.clear(), name="DocCog.item_fetcher unload clear")
