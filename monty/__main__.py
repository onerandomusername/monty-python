import asyncio
import logging
import signal
import sys

import cachingutils
import cachingutils.redis
import disnake
import redis
import redis.asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from monty import constants, monkey_patches
from monty.bot import Monty
from monty.migrations import run_alembic


log = logging.getLogger(__name__)

try:
    import uvloop  # pyright: ignore[reportMissingImports]

    uvloop.install()
    log.info("Using uvloop as event loop.")
except ImportError:
    log.info("Using default asyncio event loop.")


def get_redis_session(*, use_fakeredis: bool = False) -> redis.asyncio.Redis:
    """Create the redis session, either fakeredis or a real one based on env vars."""
    if use_fakeredis:
        try:
            import fakeredis
            import fakeredis.aioredis
        except ImportError as e:
            msg = "fakeredis must be installed to use fake redis"
            raise RuntimeError(msg) from e
        redis_session = fakeredis.aioredis.FakeRedis.from_url(constants.Redis.uri)
    else:
        pool = redis.asyncio.BlockingConnectionPool.from_url(
            constants.Redis.uri,
            max_connections=20,
            timeout=300,
        )
        redis_session = redis.asyncio.Redis(connection_pool=pool)
    return redis_session


async def main() -> None:
    """Create and run the bot."""
    # we make our redis session here and pass it to cachingutils
    if constants.Redis.use_fakeredis:
        log.warning("Using fakeredis for Redis session. This is not suitable for production use.")
    redis_session = get_redis_session(use_fakeredis=constants.Redis.use_fakeredis)

    cachingutils.redis.async_session(
        constants.Client.config_prefix, session=redis_session, prefix=constants.Redis.prefix
    )

    database_engine = create_async_engine(constants.Database.postgres_bind)
    # run alembic migrations
    if constants.Database.run_migrations:
        log.info(f"Running database migrations to target {constants.Database.migration_target}")
        await run_alembic(database_engine)
    else:
        log.info("Skipping database migrations per environment settings.")
        # we still need to connect to the database to verify connection info is correct
        async with database_engine.connect():
            pass

    # ping redis
    await redis_session.ping()
    log.debug("Successfully pinged redis server.")

    bot = Monty(
        redis_session=redis_session,
        database_engine=database_engine,
        command_prefix=constants.Client.default_command_prefix,
        activity=constants.Client.activity,
        allowed_mentions=constants.Client.allowed_mentions,
        intents=constants.Client.intents,
        command_sync_flags=constants.Client.command_sync_flags,
        proxy=constants.Client.proxy,
    )

    try:
        bot.load_extensions()
    except Exception:
        log.exception("Failed to load extensions. Shutting down.")
        await bot.close()
        raise

    loop = asyncio.get_running_loop()

    future: asyncio.Future = asyncio.ensure_future(bot.start(constants.Client.token or ""), loop=loop)

    try:
        loop.add_signal_handler(signal.SIGINT, lambda: future.cancel())
        loop.add_signal_handler(signal.SIGTERM, lambda: future.cancel())
    except NotImplementedError:
        # Signal handlers are not implemented on some platforms (e.g., Windows)
        pass
    try:
        await future
    except asyncio.CancelledError:
        log.info("Received signal to terminate bot and event loop.")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    disnake.Embed.set_default_colour(constants.Colours.python_yellow)
    monkey_patches.patch_typing()
    monkey_patches.patch_inter_send()
    sys.exit(asyncio.run(main()))
