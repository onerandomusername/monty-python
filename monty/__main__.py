import asyncio
import logging
import signal
import sys

import async_rediscache
import disnake
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

    redis_session = async_rediscache.RedisSession(
        address=(constants.RedisConfig.host, constants.RedisConfig.port),
        password=constants.RedisConfig.password,
        minsize=1,
        maxsize=20,
        use_fakeredis=constants.RedisConfig.use_fakeredis,
        global_namespace="monty-python",
    )

    await redis_session.connect()

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
    try:
        await future
    except asyncio.CancelledError:
        log.info("Received signal to terminate bot and event loop.")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
