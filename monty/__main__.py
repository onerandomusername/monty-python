import asyncio
import logging
import os
import signal
import sys

import alembic.command
import alembic.config
import cachingutils
import cachingutils.redis
import disnake
import redis.asyncio

import monty.alembic
from monty import constants, monkey_patches
from monty.bot import Monty
from monty.database.metadata import database


log = logging.getLogger(__name__)
_intents = disnake.Intents.all()
_intents.members = False
_intents.presences = False
_intents.bans = False
_intents.integrations = False
_intents.invites = False
_intents.typing = False
_intents.webhooks = False
_intents.voice_states = False


async def main() -> None:
    """Create and run the bot."""
    disnake.Embed.set_default_colour(constants.Colours.python_yellow)
    monkey_patches.patch_typing()

    # we make our redis session here and pass it to cachingutils
    if not constants.RedisConfig.use_fakeredis:

        pool = redis.asyncio.BlockingConnectionPool(
            max_connections=20,
            timeout=300,
            host=constants.RedisConfig.host,
            port=constants.RedisConfig.port,
            password=constants.RedisConfig.password,
        )
        redis_session = redis.asyncio.Redis(connection_pool=pool)

    else:
        try:
            import fakeredis
            import fakeredis.aioredis
        except ImportError as e:
            raise RuntimeError("fakeredis must be installed to use fake redis") from e
        redis_session = fakeredis.aioredis.FakeRedis()
    cachingutils.redis.async_session(
        constants.Client.config_prefix, session=redis_session, prefix=constants.RedisConfig.prefix
    )

    # run alembic migrations
    if constants.Database.run_migrations:
        log.info(f"Running database migrations to target {constants.Database.migration_target}")
        alembic_cfg = alembic.config.Config()
        alembic_cfg.set_main_option("script_location", os.path.dirname(monty.alembic.__file__))
        alembic_cfg.set_main_option("sqlalchemy.url", str(database.url))
        alembic.command.upgrade(alembic_cfg, constants.Database.migration_target)

    else:
        log.warning("Not running database migrations per environment settings.")

    # connect to the database
    await database.connect()

    bot = Monty(
        redis_session=redis_session,
        database=database,
        command_prefix=constants.Client.default_command_prefix,
        activity=disnake.Game(name=f"Commands: {constants.Client.default_command_prefix}help"),
        allowed_mentions=disnake.AllowedMentions(everyone=False),
        intents=_intents,
    )

    bot.load_extensions()
    loop = asyncio.get_running_loop()

    future: asyncio.Future = asyncio.ensure_future(bot.start(constants.Client.token), loop=loop)
    loop.add_signal_handler(signal.SIGINT, lambda: future.cancel())
    loop.add_signal_handler(signal.SIGTERM, lambda: future.cancel())
    try:
        await future
    except asyncio.CancelledError:
        log.info("Received signal to terminate bot and event loop.")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
