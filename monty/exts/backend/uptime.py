from disnake.ext import commands, tasks

from monty.bot import Monty
from monty.constants import UptimeMonitoring
from monty.log import get_logger
from monty.metadata import ExtMetadata


EXT_METADATA = ExtMetadata(core=True)
logger = get_logger(__name__)


class UptimeMonitor(commands.Cog, slash_command_attrs={"dm_permission": False}):
    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        if UptimeMonitoring.enabled:
            self.uptime_monitor.start()

    def on_cog_unload(self) -> None:
        """Stop existing tasks on cog unload."""
        self.uptime_monitor.cancel()

    @tasks.loop(seconds=UptimeMonitoring.interval)
    async def uptime_monitor(self) -> None:
        """Send an uptime ack if uptime monitoring is enabled."""
        async with self.bot.http_session.get(UptimeMonitoring.private_url):
            pass

    @uptime_monitor.before_loop
    async def before_uptime_monitor(self) -> None:
        """Wait until the bot is ready to send an uptime ack."""
        await self.bot.wait_until_ready()


def setup(bot: Monty) -> None:
    """Add the uptime monitoring cog to the bot."""
    bot.add_cog(UptimeMonitor(bot))
