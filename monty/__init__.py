try:
    import dotenv
except ModuleNotFoundError:
    pass
else:
    if dotenv.find_dotenv():
        print("Found .env file, loading environment variables from it.")  # noqa: T201
        dotenv.load_dotenv(override=True)


import asyncio
import logging
import os
from functools import partial, partialmethod

import sentry_sdk
from disnake.ext import commands
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

####################
# NOTE: do not import any other modules before the `log.setup()` call
####################
from monty import log


sentry_logging = LoggingIntegration(
    level=5,  # this is the same as logging.TRACE
    event_level=logging.WARNING,
)

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    integrations=[
        sentry_logging,
        RedisIntegration(),
    ],
    release=f"monty@{os.environ.get('GIT_SHA', 'dev')}",
)

log.setup()


from monty import monkey_patches  # noqa: E402  # we need to set up logging before importing anything else


# On Windows, the selector event loop is required for aiodns.
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Monkey-patch discord.py decorators to use the both the Command and Group subclasses which supports root aliases.
# Must be patched before any cogs are added.
commands.command = partial(commands.command, cls=monkey_patches.Command)
commands.GroupMixin.command = partialmethod(commands.GroupMixin.command, cls=monkey_patches.Command)  # type: ignore

commands.group = partial(commands.group, cls=monkey_patches.Group)
commands.GroupMixin.group = partialmethod(commands.GroupMixin.group, cls=monkey_patches.Group)  # type: ignore
