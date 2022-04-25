import asyncio
import collections
import logging
import socket
from typing import Optional

import arrow
import async_rediscache
import disnake
from aiohttp import AsyncResolver, ClientSession, TCPConnector
from disnake.ext import commands

from monty import constants
from monty.config import Database
from monty.statsd import AsyncStatsClient
from monty.utils.extensions import EXTENSIONS, walk_extensions


log = logging.getLogger(__name__)

try:
    import dotenv
except ModuleNotFoundError:
    TEST_GUILDS = None
else:
    TEST_GUILDS = dotenv.get_key(".env", "TEST_GUILDS")
    if TEST_GUILDS:
        TEST_GUILDS = [int(x.strip()) for x in TEST_GUILDS.split(",")]
        log.info("TEST_GUILDS FOUND")


__all__ = ("Bot", "bot")


class Monty(commands.Bot):
    """
    Base bot instance.

    While in debug mode, the asset upload methods (avatar, banner, ...) will not
    perform the upload, and will instead only log the passed download urls and pretend
    that the upload was successful. See the `mock_in_debug` decorator for further details.
    """

    name = constants.Client.name

    def __init__(self, redis_session: async_rediscache.RedisSession, **kwargs):
        if TEST_GUILDS:
            kwargs["test_guilds"] = TEST_GUILDS
            log.warn("registering as test_guilds")
        super().__init__(**kwargs)
        self.redis_session = redis_session
        self.http_session = ClientSession(connector=TCPConnector(resolver=AsyncResolver(), family=socket.AF_INET))

        self.db = Database()
        self.socket_events = collections.Counter()
        self.start_time: arrow.Arrow = None
        self.stats: AsyncStatsClient = None
        self.invite_permissions: disnake.Permissions = constants.Client.invite_permissions
        self.loop.create_task(self.get_self_invite_perms())

    async def get_self_invite_perms(self) -> disnake.Permissions:
        """Sets the internal invite_permissions and fetches them."""
        await self.wait_until_first_connect()
        app_info = await self.application_info()
        if app_info.install_params:
            self.invite_permissions = app_info.install_params.permissions
        else:
            self.invite_permissions = constants.Client.invite_permissions
        return self.invite_permissions

    async def login(self, token: str) -> None:
        """Login to Discord and set the bot's start time."""
        self.start_time = arrow.utcnow()
        self.stats = AsyncStatsClient(
            host=constants.Stats.host,
            port=constants.Stats.port,
            prefix=constants.Stats.prefix,
        )
        return await super().login(token)

    async def close(self) -> None:
        """Close sessions when bot is shutting down."""
        await super().close()

        await self.db.close()

        if self.http_session:
            await self.http_session.close()

    def load_extensions(self) -> None:
        """Load all extensions as released by walk_extensions()."""
        if constants.Client.extensions:
            log.warning("Not loading all extensions as per environment settings.")
        EXTENSIONS.update(walk_extensions())
        for ext, metadata in walk_extensions():
            if not constants.Client.extensions:
                self.load_extension(ext)
                continue

            if metadata.core or ext in constants.Client.extensions:
                self.load_extension(ext)
                continue
            log.trace(f"SKIPPING loading {ext} as per environment variables.")
        log.info("Completed loading extensions.")

    def add_cog(self, cog: commands.Cog) -> None:
        """
        Delegate to super to register `cog`.

        This only serves to make the info log, so that extensions don't have to.
        """
        super().add_cog(cog)
        log.info(f"Cog loaded: {cog.qualified_name}")

    def add_command(self, command: commands.Command) -> None:
        """Add `command` as normal and then add its root aliases to the bot."""
        super().add_command(command)
        self._add_root_aliases(command)

    def remove_command(self, name: str) -> Optional[commands.Command]:
        """
        Remove a command/alias as normal and then remove its root aliases from the bot.

        Individual root aliases cannot be removed by this function.
        To remove them, either remove the entire command or manually edit `bot.all_commands`.
        """
        command = super().remove_command(name)
        if command is None:
            # Even if it's a root alias, there's no way to get the Bot instance to remove the alias.
            return

        self._remove_root_aliases(command)
        return command

    async def on_command_error(self, context: commands.Context, exception: disnake.DiscordException) -> None:
        """Check command errors for UserInputError and reset the cooldown if thrown."""
        if isinstance(exception, commands.UserInputError):
            context.command.reset_cooldown(context)
        else:
            await super().on_command_error(context, exception)

    def _add_root_aliases(self, command: commands.Command) -> None:
        """Recursively add root aliases for `command` and any of its subcommands."""
        if isinstance(command, commands.Group):
            for subcommand in command.commands:
                self._add_root_aliases(subcommand)

        for alias in getattr(command, "root_aliases", ()):
            if alias in self.all_commands:
                raise commands.CommandRegistrationError(alias, alias_conflict=True)

            self.all_commands[alias] = command

    def _remove_root_aliases(self, command: commands.Command) -> None:
        """Recursively remove root aliases for `command` and any of its subcommands."""
        if isinstance(command, commands.Group):
            for subcommand in command.commands:
                self._remove_root_aliases(subcommand)

        for alias in getattr(command, "root_aliases", ()):
            self.all_commands.pop(alias, None)


# temp: for backwards compatibilty
Bot = Monty

_intents = disnake.Intents.all()
_intents.members = False
_intents.presences = False
_intents.bans = False
_intents.integrations = False
_intents.invites = False
_intents.typing = False
_intents.webhooks = False
_intents.voice_states = False

redis_session = async_rediscache.RedisSession(
    address=(constants.RedisConfig.host, constants.RedisConfig.port),
    password=constants.RedisConfig.password,
    minsize=1,
    maxsize=20,
    use_fakeredis=constants.RedisConfig.use_fakeredis,
    global_namespace="monty-python",
)

loop = asyncio.get_event_loop()
loop.run_until_complete(redis_session.connect())

bot = Monty(
    redis_session=redis_session,
    command_prefix=commands.when_mentioned_or(constants.Client.prefix),
    activity=disnake.Game(name=f"Commands: {constants.Client.prefix}help"),
    allowed_mentions=disnake.AllowedMentions(everyone=False),
    intents=_intents,
)

loop.run_until_complete(bot.db.async_init())
