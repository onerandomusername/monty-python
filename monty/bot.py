import collections
import logging
import socket
from types import SimpleNamespace
from typing import Optional

import aiohttp
import arrow
import cachingutils.redis
import disnake
import redis.asyncio
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


__all__ = ("Bot",)


class Monty(commands.Bot):
    """
    Base bot instance.

    While in debug mode, the asset upload methods (avatar, banner, ...) will not
    perform the upload, and will instead only log the passed download urls and pretend
    that the upload was successful. See the `mock_in_debug` decorator for further details.
    """

    name = constants.Client.name

    def __init__(self, redis_session: redis.asyncio.Redis, **kwargs):
        if TEST_GUILDS:
            kwargs["test_guilds"] = TEST_GUILDS
            log.warn("registering as test_guilds")
        super().__init__(**kwargs)

        self.redis_session = redis_session
        self.redis_cache = cachingutils.redis.async_session(constants.Client.redis_prefix, session=self.redis_session)
        self.redis_cache_key = constants.Client.redis_prefix

        self.create_http_session()

        self.db = Database()
        self.socket_events = collections.Counter()
        self.start_time: arrow.Arrow = None
        self.stats: AsyncStatsClient = None
        self.invite_permissions: disnake.Permissions = constants.Client.invite_permissions
        self.loop.create_task(self.get_self_invite_perms())

    def create_http_session(self) -> None:
        """Create the aiohttp session and set the trace logger, if desired."""
        trace_configs = []
        if constants.Client.debug:
            aiohttp_log = logging.getLogger(__package__ + ".http")

            async def on_request_end(
                session: aiohttp.ClientSession,
                ctx: SimpleNamespace,
                end: aiohttp.TraceRequestEndParams,
            ) -> None:
                """Log all aiohttp requests on request end."""
                resp = end.response
                aiohttp_log.info(
                    "[{status!s} {reason!s}] {method!s} {url!s} ({content_type!s})".format(
                        status=resp.status,
                        reason=resp.reason,
                        method=end.method.upper(),
                        url=end.url,
                        content_type=resp.content_type,
                    )
                )

            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_end.append(on_request_end)
            trace_configs.append(trace_config)

        self.http_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=aiohttp.AsyncResolver(), family=socket.AF_INET),
            trace_configs=trace_configs,
        )

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
