import yarl
from disnake.ext import commands, tasks

from monty.bot import Monty
from monty.constants import UptimeMonitoring
from monty.log import get_logger
from monty.metadata import ExtMetadata


EXT_METADATA = ExtMetadata(core=True)
logger = get_logger(__name__)


class UptimeMonitor(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Pong a remote server for uptime monitoring."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self._url = yarl.URL(UptimeMonitoring.private_url)
        if UptimeMonitoring.enabled:
            self.uptime_monitor.start()

    def cog_unload(self) -> None:
        """Stop existing tasks on cog unload."""
        self.uptime_monitor.cancel()

    def get_url(self) -> str:
        """Get the uptime URL with proper formatting. The result of this method should not be cached."""
        queries = {}
        for param, value in UptimeMonitoring.query_params.items():
            if callable(value):
                value = value(self.bot)
            queries[param] = value

        return str(self._url.update_query(**queries))

    @tasks.loop(seconds=UptimeMonitoring.interval)
    async def uptime_monitor(self) -> None:
        """Send an uptime ack if uptime monitoring is enabled."""
        url = self.get_url()
        async with self.bot.http_session.get(url, use_cache=False):
            pass

    @uptime_monitor.before_loop
    async def before_uptime_monitor(self) -> None:
        """Wait until the bot is ready to send an uptime ack."""
        await self.bot.wait_until_ready()


def setup(bot: Monty) -> None:
    """Add the uptime monitoring cog to the bot."""
    bot.add_cog(UptimeMonitor(bot))
