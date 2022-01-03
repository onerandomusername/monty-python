import logging

from monty.bot import bot
from monty.constants import Client


log = logging.getLogger(__name__)


bot.load_extensions()
bot.run(Client.token)
