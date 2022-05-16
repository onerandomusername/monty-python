import asyncio
import logging
import signal
import sys

import cachingutils
import cachingutils.redis
import disnake
import redis.asyncio
from disnake.ext import commands

from monty import constants
from monty.bot import Monty


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

    bot = Monty(
        redis_session=redis_session,
        command_prefix=commands.when_mentioned_or(constants.Client.prefix),
        activity=disnake.Game(name=f"Commands: {constants.Client.prefix}help"),
        allowed_mentions=disnake.AllowedMentions(everyone=False),
        intents=_intents,
    )

    await bot.db.async_init()

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
