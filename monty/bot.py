import asyncio
import collections
import socket
from types import SimpleNamespace
from typing import Optional, Union
from weakref import WeakValueDictionary

import aiohttp
import arrow
import cachingutils.redis
import databases
import disnake
import redis.asyncio
from disnake.ext import commands

from monty import constants
from monty.database import Feature, Guild, GuildConfig
from monty.database.metadata import metadata
from monty.database.rollouts import Rollout
from monty.log import get_logger
from monty.statsd import AsyncStatsClient
from monty.utils import rollouts
from monty.utils.extensions import EXTENSIONS, walk_extensions


log = get_logger(__name__)

try:
    import dotenv
except ModuleNotFoundError:
    TEST_GUILDS = None
else:
    TEST_GUILDS = dotenv.get_key(".env", "TEST_GUILDS")
    if TEST_GUILDS:
        TEST_GUILDS = [int(x.strip()) for x in TEST_GUILDS.split(",")]
        log.info("TEST_GUILDS FOUND")


__all__ = ("Monty",)


class Monty(commands.Bot):
    """
    Base bot instance.

    While in debug mode, the asset upload methods (avatar, banner, ...) will not
    perform the upload, and will instead only log the passed download urls and pretend
    that the upload was successful. See the `mock_in_debug` decorator for further details.
    """

    name = constants.Client.name

    def __init__(self, redis_session: redis.asyncio.Redis, database: databases.Database, **kwargs):
        if TEST_GUILDS:
            kwargs["test_guilds"] = TEST_GUILDS
            log.warn("registering as test_guilds")
        kwargs["sync_commands_on_cog_unload"] = False
        super().__init__(**kwargs)

        self.redis_session = redis_session
        self.redis_cache = cachingutils.redis.async_session(constants.Client.redis_prefix, session=self.redis_session)
        self.redis_cache_key = constants.Client.redis_prefix

        self.create_http_session()

        self.db: databases.Database = database
        self.db_metadata = metadata
        self.guild_configs: dict[int, GuildConfig] = {}
        self.guild_db: dict[int, Guild] = {}
        self.features: dict[str, Feature] = {}
        self._feature_db_lock = asyncio.Lock()
        self._guild_db_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

        self.socket_events = collections.Counter()
        self.start_time: arrow.Arrow
        self.stats: AsyncStatsClient
        self.command_prefix: str
        self.invite_permissions: disnake.Permissions = constants.Client.invite_permissions
        self.loop.create_task(self.get_self_invite_perms())

    def create_http_session(self) -> None:
        """Create the aiohttp session and set the trace logger, if desired."""
        trace_configs = []
        if constants.Client.debug:
            aiohttp_log = get_logger(__package__ + ".http")

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

    async def ensure_guild(self, guild_id: int) -> Guild:
        """Fetch and return a guild config, creating if it does not exist."""
        guild = self.guild_db.get(guild_id)
        if not guild:
            lock = self._guild_db_locks.get(guild_id)
            if not lock:
                lock = self._guild_db_locks[guild_id] = asyncio.Lock()
            async with lock:
                # once again use the cache just in case
                guild = self.guild_db.get(guild_id)
                if not guild:
                    guild, _ = await Guild.objects.get_or_create(id=guild_id)
                    self.guild_db[guild_id] = guild
        return guild

    async def ensure_guild_config(self, guild_id: int) -> GuildConfig:
        """Fetch and return a guild config, creating if it does not exist."""
        config = self.guild_configs.get(guild_id)
        if not config:
            config, _ = await GuildConfig.objects.get_or_create(id=guild_id)
            self.guild_configs[guild_id] = config

        if not config.guild:
            guild = await self.ensure_guild(guild_id)
            config.guild = guild
            await config.update()

        return config

    async def get_prefix(self, message: disnake.Message) -> Optional[Union[list[str], str]]:
        """Get the bot prefix."""
        prefixes = commands.when_mentioned(self, message)
        if message.guild:
            config = await self.ensure_guild_config(message.guild.id)
            if config and config.prefix:
                prefixes.insert(0, config.prefix)
            else:
                prefixes.insert(0, self.command_prefix)
        return prefixes

    async def refresh_features(self) -> None:
        """Refresh the feature cache."""
        async with self._feature_db_lock:
            features = await Feature.objects.all()
            full_features = []
            for feature in features:
                full_features.append(await feature.load_all())
            self.features.clear()
            self.features.update({feature.name: feature for feature in full_features})

    async def guild_has_feature(
        self,
        guild: Optional[Union[int, disnake.abc.Snowflake]],
        feature: str,
        *,
        include_feature_status: bool = True,
        create_if_not_exists: bool = True,
    ) -> bool:
        """
        Return whether or not the provided guild has the provided feature.

        By default, this considers the feature's enabled status,
        which can be disabled with `include_feature_status` set to False.
        """
        # first create the feature if we are told to create it
        if feature in self.features:
            feature_instance = self.features[feature]
        else:
            # if its not cached
            # we don't need to seperate this based on features as we aren't creating features that often
            async with self._feature_db_lock:
                # attempt a fetch first
                # get from cached features once within the lock
                feature_instance = self.features.get(feature)
                if not feature_instance:
                    feature_instance = await Feature.objects.get_or_none(name=feature)
                    if not feature_instance and create_if_not_exists:
                        feature_instance = self.features[feature] = await Feature.objects.create(name=feature)
                    elif feature_instance:
                        feature_instance = self.features[feature] = await feature_instance.load_all()
        # we're defaulting to non-existing features as None, rather than False.
        # this might change later.
        if include_feature_status and feature_instance:
            if feature_instance.enabled is not None:
                return feature_instance.enabled

        # the feature's enabled status is None, so we should check the guild
        # support the guild being None to make it easier to use
        if guild is None:
            return False
        if not isinstance(guild, int):
            guild = guild.id

        guild_db = await self.ensure_guild(guild)
        if feature in guild_db.features:
            return True

        # check if this feature has an active rollout
        if feature_instance and feature_instance.rollout:
            if not feature_instance.rollout.saved:
                feature_instance.rollout = await Rollout.objects.get(id=feature_instance.rollout.id)

            return rollouts.is_rolled_out_to(guild, rollout=feature_instance.rollout)

        return False

    async def on_connect(self) -> None:
        """Fetch the list of features once we create our internal sessions."""
        self.features.update({feature.name: feature for feature in await Feature.objects.all()})
        log.info("Fetched the features from the database.")

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

        if self.http_session:
            await self.http_session.close()

        if self.redis_session:
            await self.redis_session.close(close_connection_pool=True)

        if self.db:
            await self.db.disconnect()

    def load_extensions(self) -> None:
        """Load all extensions as released by walk_extensions()."""
        if constants.Client.extensions:
            log.warning("Not loading all extensions as per environment settings.")
        EXTENSIONS.update(walk_extensions())
        for ext, ext_metadata in walk_extensions():
            if not constants.Client.extensions:
                self.load_extension(ext)
                continue

            if ext_metadata.core or ext in constants.Client.extensions:
                self.load_extension(ext)
                continue
            log.debug(f"SKIPPING loading {ext} as per environment variables.")
        log.info("Completed loading extensions.")

    def add_cog(self, cog: commands.Cog) -> None:
        """
        Delegate to super to register `cog`.

        This only serves to make the info log, so that extensions don't have to.
        """
        super().add_cog(cog)
        log.info(f"Cog loaded: {cog.qualified_name}")
        self.dispatch("cog_load", cog)

    def remove_cog(self, name: str) -> Optional[commands.Cog]:
        """Remove the cog from the bot and dispatch a cog_remove event."""
        cog = super().remove_cog(name)
        if cog is None:
            return None
        self.dispatch("cog_remove", cog)
        return cog

    def add_command(self, command: commands.Command) -> None:
        """Add `command` as normal and then add its root aliases to the bot."""
        super().add_command(command)
        self._add_root_aliases(command)
        self.dispatch("command_add", command)

    def remove_command(self, name: str) -> Optional[commands.Command]:
        """
        Remove a command/alias as normal and then remove its root aliases from the bot.

        This also dispatches the command_remove event.

        Individual root aliases cannot be removed by this function.
        To remove them, either remove the entire command or manually edit `bot.all_commands`.
        """
        command = super().remove_command(name)
        if command is None:
            # Even if it's a root alias, there's no way to get the Bot instance to remove the alias.
            return

        self.dispatch("command_remove", command)
        self._remove_root_aliases(command)
        return command

    def add_slash_command(self, slash_command: commands.InvokableSlashCommand) -> None:
        """Add the slash command to the bot and dispatch a slash_command_add event."""
        super().add_slash_command(slash_command)
        self.dispatch("slash_command_add", slash_command)

    def remove_slash_command(self, name: str) -> Optional[commands.InvokableSlashCommand]:
        """Remove the slash command from the bot and dispatch a slash_command_remove event."""
        slash_command = super().remove_slash_command(name)
        if slash_command is None:
            return None
        self.dispatch("slash_command_remove", slash_command)
        return slash_command

    async def on_command_error(self, context: commands.Context, exception: disnake.DiscordException) -> None:
        """Check command errors for UserInputError and reset the cooldown if thrown."""
        if isinstance(exception, commands.UserInputError) and context.command:
            context.command.reset_cooldown(context)
        else:
            await super().on_command_error(context, exception)  # type:ignore

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
