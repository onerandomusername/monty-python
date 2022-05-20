try:
    import dotenv
except ModuleNotFoundError:
    pass
else:
    if dotenv.find_dotenv():
        print("Found .env file, loading environment variables from it.")
        dotenv.load_dotenv(override=True)


import asyncio
import os
from functools import partial, partialmethod

from disnake.ext import commands

from monty import log, monkey_patches


log.setup()

# On Windows, the selector event loop is required for aiodns.
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Monkey-patch discord.py decorators to use the both the Command and Group subclasses which supports root aliases.
# Must be patched before any cogs are added.
commands.command = partial(commands.command, cls=monkey_patches.Command)
commands.GroupMixin.command = partialmethod(commands.GroupMixin.command, cls=monkey_patches.Command)

commands.group = partial(commands.group, cls=monkey_patches.Group)
commands.GroupMixin.group = partialmethod(commands.GroupMixin.group, cls=monkey_patches.Group)
