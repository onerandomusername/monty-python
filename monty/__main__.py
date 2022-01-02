import logging

from monty.bot import bot
from monty.constants import Client
from monty.utils.extensions import walk_extensions


log = logging.getLogger(__name__)


for ext in walk_extensions():
    bot.load_extension(ext)

bot.run(Client.token)
