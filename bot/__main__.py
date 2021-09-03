import logging

from bot.bot import bot
from bot.constants import Client
from bot.utils.extensions import walk_extensions


log = logging.getLogger(__name__)


for ext in walk_extensions():
    bot.load_extension(ext)

bot.run(Client.token)
