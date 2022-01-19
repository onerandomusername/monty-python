import logging

import disnake

from monty.bot import bot
from monty.constants import Client


log = logging.getLogger(__name__)

disnake.Embed.set_default_colour(0x3575A8)
bot.load_extensions()
bot.run(Client.token)
