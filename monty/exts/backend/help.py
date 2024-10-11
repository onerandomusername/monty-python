# Help command from Python bot. All commands that will be added to there in futures should be added to here too.
import asyncio
import itertools
from contextlib import suppress
from typing import List, NamedTuple, Optional, Union

import disnake
from disnake.ext import commands
from rapidfuzz import fuzz, process

from monty import constants
from monty.bot import Monty
from monty.constants import Emojis
from monty.log import get_logger
from monty.metadata import ExtMetadata
from monty.utils import scheduling
from monty.utils.pagination import FIRST_EMOJI, LAST_EMOJI, LEFT_EMOJI, RIGHT_EMOJI, LinePaginator


TIMEOUT = 90
EXT_METADATA = ExtMetadata(core=True)

DELETE_EMOJI = Emojis.trashcan
CUSTOM_ID_PREFIX = "paginator_page"
PAGINATION_EMOJI: dict[str, str] = {
    "first": FIRST_EMOJI,
    "back": LEFT_EMOJI,
    "next": RIGHT_EMOJI,
    "end": LAST_EMOJI,
    "stop": DELETE_EMOJI,
}


class Cog(NamedTuple):
    """Show information about a Cog's name, description and commands."""

    name: str
    description: str
    commands: List[commands.Command]


log = get_logger(__name__)


class HelpQueryNotFound(ValueError):
    """
    Raised when a HelpSession Query doesn't match a command or cog.

    Contains the custom attribute of ``possible_matches``.
    Instances of this object contain a dictionary of any command(s) that were close to matching the
    query, where keys are the possible matched command names and values are the likeness match scores.
    """

    def __init__(self, arg: str, possible_matches: dict = None) -> None:
        super().__init__(arg)
        self.possible_matches = possible_matches


class HelpSession:
    """
    An interactive session for bot and command help output.

    Expected attributes include:
        * title: str
            The title of the help message.
        * query: Union[disnake.ext.commands.Bot, disnake.ext.commands.Command]
        * description: str
            The description of the query.
        * pages: list[str]
            A list of the help content split into manageable pages.
        * message: `discord.Message`
            The message object that's showing the help contents.
        * destination: `discord.abc.Messageable`
            Where the help message is to be sent to.
    Cogs can be grouped into custom categories. All cogs with the same category will be displayed
    under a single category name in the help output. Custom categories are defined inside the cogs
    as a class attribute named `category`. A description can also be specified with the attribute
    `category_description`. If a description is not found in at least one cog, the default will be
    the regular description (class docstring) of the first cog found in the category.
    """

    def __init__(
        self,
        ctx: commands.Context,
        *command,
        cleanup: bool = False,
        only_can_run: bool = True,
        show_hidden: bool = False,
        max_lines: int = 15,
    ) -> None:
        """Creates an instance of the HelpSession class."""
        self._ctx = ctx
        self._bot: Monty = ctx.bot
        self.title = "Command Help"

        # set the query details for the session
        if command:
            query_str = " ".join(command)
            self.query = self._get_query(query_str)
            self.description = self.query.description or self.query.help
        else:
            self.query = ctx.bot
            self.description = self.query.description
        self.author = ctx.author
        self.destination = ctx.channel

        # set the config for the session
        self._cleanup = cleanup
        self._only_can_run = only_can_run
        self._show_hidden = show_hidden
        self._max_lines = max_lines

        # init session states
        self._pages = None
        self._current_page = 0
        self.message = None
        self._timeout_task = None
        self.reset_timeout()

    def _get_query(self, query: str) -> Union[commands.Command, Cog]:
        """Attempts to match the provided query with a valid command or cog."""
        command = self._bot.get_command(query)
        if command:
            return command

        # Find all cog categories that match.
        cog_matches = []
        description = None
        for cog in self._bot.cogs.values():
            if hasattr(cog, "category") and cog.category == query:
                cog_matches.append(cog)
                if hasattr(cog, "category_description"):
                    description = cog.category_description

        # Try to search by cog name if no categories match.
        if not cog_matches:
            cog = self._bot.cogs.get(query)

            # Don't consider it a match if the cog has a category.
            if cog and not hasattr(cog, "category"):
                cog_matches = [cog]

        if cog_matches:
            cog = cog_matches[0]
            cmds = (cog.get_commands() for cog in cog_matches)  # Commands of all cogs

            return Cog(
                name=cog.category if hasattr(cog, "category") else cog.qualified_name,
                description=description or cog.description,
                commands=tuple(itertools.chain.from_iterable(cmds)),  # Flatten the list
            )

        self._handle_not_found(query)

    def _handle_not_found(self, query: str) -> None:
        """
        Handles when a query does not match a valid command or cog.

        Will pass on possible close matches along with the `HelpQueryNotFound` exception.
        """
        # Combine command and cog names
        choices = list(self._bot.all_commands) + list(self._bot.cogs)

        result = process.extract(query, choices, score_cutoff=60, scorer=fuzz.ratio)

        raise HelpQueryNotFound(f'Query "{query}" not found.', {choice: score for choice, score, pos in result})

    async def timeout(self, seconds: int = TIMEOUT) -> None:
        """Waits for a set number of seconds, then stops the help session."""
        await asyncio.sleep(seconds)
        await self.stop()

    @staticmethod
    def strip_custom_id(custom_id: str) -> Optional[str]:
        """Remove paginator custom id prefix."""
        if not custom_id.startswith(CUSTOM_ID_PREFIX):
            return None

        return custom_id[len(CUSTOM_ID_PREFIX) :]

    def reset_timeout(self) -> None:
        """Cancels the original timeout task and sets it again from the start."""
        # cancel original if it exists
        if self._timeout_task:
            if not self._timeout_task.cancelled():
                self._timeout_task.cancel()

        # recreate the timeout task
        self._timeout_task = scheduling.create_task(self.timeout())

    async def on_message_interaction(self, inter: disnake.MessageInteraction) -> None:
        """Event handler for when reactions are added on the help message."""
        # ensure it was the relevant session message
        if not self.message:
            return

        if inter.message.id != self.message.id:
            return
        name = self.strip_custom_id(inter.data.custom_id)
        if name is None or name not in PAGINATION_EMOJI:
            return

        # ensure it was the session author who reacted
        if inter.author.id != self.author.id:
            await inter.response.defer()
            return

        self.reset_timeout()

        # Run relevant action method
        action = getattr(self, f"do_{name}", None)
        if not action:
            return
        self.inter = inter
        await action()
        if not inter.response.is_done():
            await inter.response.defer()

    async def on_message_delete(self, message: disnake.Message) -> None:
        """Closes the help session when the help message is deleted."""
        if self.message and message.id == self.message.id:
            await self.stop()

    async def prepare(self) -> None:
        """Sets up the help session pages, events, message and reactions."""
        await self.build_pages()

        self._bot.add_listener(self.on_message_interaction)
        self._bot.add_listener(self.on_message_delete)

        await self.update_page()

    def _category_key(self, cmd: commands.Command) -> str:
        """
        Returns a cog name of a given command for use as a key for `sorted` and `groupby`.

        A zero width space is used as a prefix for results with no cogs to force them last in ordering.
        """
        if cmd.cog:
            try:
                if cmd.cog.category:
                    return f"**{cmd.cog.category}**"
            except AttributeError:
                pass

            return f"**{cmd.cog_name}**"
        else:
            return "**\u200bNo Category:**"

    def _get_command_params(self, cmd: commands.Command) -> str:
        """
        Returns the command usage signature.

        This is a custom implementation of `command.signature` in order to format the command
        signature without aliases.
        """
        results = []
        for name, param in cmd.clean_params.items():
            # if argument has a default value
            if param.default is not param.empty:
                if isinstance(param.default, str):
                    show_default = param.default
                else:
                    show_default = param.default is not None

                # if default is not an empty string or None
                if show_default:
                    results.append(f"[{name}={param.default}]")
                else:
                    results.append(f"[{name}]")

            # if variable length argument
            elif param.kind == param.VAR_POSITIONAL:
                results.append(f"[{name}...]")

            # if required
            else:
                results.append(f"<{name}>")

        return f"{cmd.name} {' '.join(results)}"

    async def build_pages(self) -> None:
        """Builds the list of content pages to be paginated through in the help message, as a list of str."""
        # Use LinePaginator to restrict embed line height
        paginator = LinePaginator(prefix="", suffix="", max_lines=self._max_lines)

        # show signature if query is a command
        if isinstance(self.query, commands.Command):
            await self._add_command_signature(paginator)

        if isinstance(self.query, Cog):
            paginator.add_line(f"**{self.query.name}**")

        if self.description:
            paginator.add_line(f"*{self.description}*")

        # list all children commands of the queried object
        if isinstance(self.query, (commands.GroupMixin, Cog)):
            await self._list_child_commands(paginator)

        self._pages = paginator.pages

    async def _add_command_signature(self, paginator: LinePaginator) -> None:
        prefix = ""

        signature = self._get_command_params(self.query)
        parent = self.query.full_parent_name + " " if self.query.parent else ""
        paginator.add_line(f"**```{prefix}{parent}{signature}```**")
        aliases = [f"`{alias}`" if not parent else f"`{parent} {alias}`" for alias in self.query.aliases]
        aliases += [f"`{alias}`" for alias in getattr(self.query, "root_aliases", ())]
        aliases = ", ".join(sorted(aliases))
        if aliases:
            paginator.add_line(f"**Can also use:** {aliases}\n")
        if not await self.query.can_run(self._ctx):
            paginator.add_line("***You cannot run this command.***\n")

    async def _list_child_commands(self, paginator: LinePaginator) -> None:
        # remove hidden commands if session is not wanting hiddens
        if not self._show_hidden:
            filtered = [c for c in self.query.commands if not c.hidden]
        else:
            filtered = self.query.commands

        # if after filter there are no commands, finish up
        if not filtered:
            self._pages = paginator.pages
            return

        if isinstance(self.query, Cog):
            grouped = (("**Commands:**", self.query.commands),)

        elif isinstance(self.query, commands.Command):
            grouped = (("**Subcommands:**", self.query.commands),)

        # otherwise sort and organise all commands into categories
        else:
            cat_sort = sorted(filtered, key=self._category_key)
            grouped = itertools.groupby(cat_sort, key=self._category_key)

        for category, cmds in grouped:
            await self._format_command_category(paginator, category, list(cmds))

    async def _format_command_category(
        self, paginator: LinePaginator, category: str, cmds: List[commands.Command]
    ) -> None:
        cmds = sorted(cmds, key=lambda c: c.name)
        cat_cmds = []
        for command in cmds:
            cat_cmds += await self._format_command(command)

        # state var for if the category should be added next
        print_cat = 1
        new_page = True

        for details in cat_cmds:
            # keep details together, paginating early if it won"t fit
            lines_adding = len(details.split("\n")) + print_cat
            if paginator._linecount + lines_adding > self._max_lines:
                paginator._linecount = 0
                new_page = True
                paginator.close_page()

                # new page so print category title again
                print_cat = 1

            if print_cat:
                if new_page:
                    paginator.add_line("")
                paginator.add_line(category)
                print_cat = 0

            paginator.add_line(details)

    async def _format_command(self, command: commands.Command) -> List[str]:
        # skip if hidden and hide if session is set to
        if command.hidden and not self._show_hidden:
            return []

        # Patch to make the !help command work outside of #bot-commands again
        # This probably needs a proper rewrite, but this will make it work in
        # the mean time.
        try:
            can_run = await command.can_run(self._ctx)
        except commands.CheckFailure:
            can_run = False

        # see if the user can run the command
        strikeout = ""
        if not can_run:
            # skip if we don't show commands they can't run
            if self._only_can_run:
                return []
            strikeout = "~~"

        prefix = ""

        signature = self._get_command_params(command)
        info = f"{strikeout}**`{prefix}{signature}`**{strikeout}"

        # handle if the command has no docstring
        short_doc = command.short_doc or "No details provided"
        return [f"{info}\n*{short_doc}*"]

    def embed_page(self, page_number: int = 0) -> disnake.Embed:
        """Returns an disnake.Embed with the requested page formatted within."""
        embed = disnake.Embed()

        if isinstance(self.query, (commands.Command, Cog)) and page_number > 0:
            title = f'Command Help | "{self.query.name}"'
        else:
            title = self.title

        embed.set_author(name=title, icon_url=constants.Icons.questionmark)
        embed.description = self._pages[page_number]

        page_count = len(self._pages)
        if page_count > 1:
            embed.set_footer(text=f"Page {self._current_page+1} / {page_count}")

        return embed

    async def update_page(self, page_number: int = 0) -> None:
        """Sends the intial message, or changes the existing one to the given page number."""
        self._current_page = page_number
        embed_page = self.embed_page(page_number)

        if not self.message:
            # build view and send it
            view = disnake.ui.View()
            for id, emoji in PAGINATION_EMOJI.items():
                view.add_item(
                    disnake.ui.Button(style=disnake.ButtonStyle.gray, custom_id=CUSTOM_ID_PREFIX + id, emoji=emoji)
                )
            self.message = await self.destination.send(embed=embed_page, view=view)
        else:
            await self.inter.response.edit_message(embed=embed_page)
            del self.inter

    @classmethod
    async def start(cls, ctx: commands.Context, *command, **options) -> "HelpSession":
        """
        Create and begin a help session based on the given command context.

        Available options kwargs:
            * cleanup: Optional[bool]
                Set to `True` to have the message deleted on session end. Defaults to `False`.
            * only_can_run: Optional[bool]
                Set to `True` to hide commands the user can't run. Defaults to `False`.
            * show_hidden: Optional[bool]
                Set to `True` to include hidden commands. Defaults to `False`.
            * max_lines: Optional[int]
                Sets the max number of lines the paginator will add to a single page. Defaults to 20.
        """
        session = cls(ctx, *command, **options)
        await session.prepare()

        return session

    async def stop(self) -> None:
        """Stops the help session, removes event listeners and attempts to delete the help message."""
        self._bot.remove_listener(self.on_message_interaction)
        self._bot.remove_listener(self.on_message_delete)
        if not self.message:
            return

        # ignore if permission issue, or the message doesn't exist
        with suppress(disnake.HTTPException, AttributeError):
            if self._cleanup:
                await self.message.delete()
            else:
                view = disnake.ui.View.from_message(self.message, timeout=1)
                for child in view.children:
                    if hasattr(child, "disabled") and child.is_dispatchable():
                        child.disabled = True
                await self.message.edit(view=view)

    @property
    def is_first_page(self) -> bool:
        """Check if session is currently showing the first page."""
        return self._current_page == 0

    @property
    def is_last_page(self) -> bool:
        """Check if the session is currently showing the last page."""
        return self._current_page == (len(self._pages) - 1)

    async def do_first(self) -> None:
        """Event that is called when the user requests the first page."""
        if not self.is_first_page:
            await self.update_page(0)

    async def do_back(self) -> None:
        """Event that is called when the user requests the previous page."""
        if not self.is_first_page:
            await self.update_page(self._current_page - 1)

    async def do_next(self) -> None:
        """Event that is called when the user requests the next page."""
        if not self.is_last_page:
            await self.update_page(self._current_page + 1)

    async def do_end(self) -> None:
        """Event that is called when the user requests the last page."""
        if not self.is_last_page:
            await self.update_page(len(self._pages) - 1)

    async def do_stop(self) -> None:
        """Event that is called when the user requests to stop the help session."""
        if self.message:
            await self.message.delete()


class Help(commands.Cog):
    """Custom disnake.Embed Pagination Help feature."""

    @commands.command("help")
    async def new_help(self, ctx: commands.Context, *commands) -> None:
        """Shows Command Help."""
        try:
            await HelpSession.start(ctx, *commands)
        except HelpQueryNotFound as error:
            embed = disnake.Embed()
            embed.colour = disnake.Colour.red()
            embed.title = str(error)

            if error.possible_matches:
                matches = "\n".join(error.possible_matches.keys())
                embed.description = f"**Did you mean:**\n`{matches}`"

            await ctx.send(embed=embed)


def unload(bot: Monty) -> None:
    """
    Reinstates the original help command.

    This is run if the cog raises an exception on load, or if the extension is unloaded.
    """
    bot.remove_command("help")
    bot.add_command(bot._old_help)


def setup(bot: Monty) -> None:
    """
    The setup for the help extension.

    This is called automatically on `bot.load_extension` being run.
    Stores the original help command instance on the `bot._old_help` attribute for later
    reinstatement, before removing it from the command registry so the new help command can be
    loaded successfully.
    If an exception is raised during the loading of the cog, `unload` will be called in order to
    reinstate the original help command.
    """
    bot._old_help = bot.get_command("help")
    bot.remove_command("help")

    try:
        bot.add_cog(Help())
    except Exception:
        unload(bot)
        raise


def teardown(bot: Monty) -> None:
    """
    The teardown for the help extension.

    This is called automatically on `bot.unload_extension` being run.
    Calls `unload` in order to reinstate the original help command.
    """
    unload(bot)
