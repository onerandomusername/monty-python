import re

from disnake import Message
from disnake.ext.commands import Cog

from monty.bot import Bot
from monty.constants import Guilds
from monty.log import get_logger
from monty.utils.messages import format_user


WEBHOOK_URL_RE = re.compile(
    r"((?:https?:\/\/)?(?:ptb\.|canary\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/)\S+\/?", re.IGNORECASE
)

ALERT_MESSAGE_TEMPLATE = (
    "{user}, looks like you posted a Discord webhook URL. Therefore "
    "your webhook has been deleted. "
    "You can re-create it if you wish to. If you believe this was a "
    "mistake, please let us know."
)

WHITELIST = [Guilds.disnake, Guilds.nextcord]

log = get_logger(__name__)


class WebhookRemover(Cog):
    """Scan messages to detect Discord webhooks links."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def maybe_delete(self, msg: Message) -> bool:
        """
        Maybe delete a message, if we have perms.

        Returns True on success.
        """
        can_delete = msg.author == msg.guild.me or msg.channel.permissions_for(msg.guild.me).manage_messages
        if not can_delete:
            return False

        await msg.delete()
        return True

    async def delete_and_respond(self, msg: Message, redacted_url: str, *, webhook_deleted: bool) -> None:
        """Delete `msg` and send a warning that it contained the Discord webhook `redacted_url`."""
        # Don't log this, due internal delete, not by user. Will make different entry.

        # try:
        #     await self.maybe_delete(msg)
        # except NotFound:
        #     log.debug(f"Failed to remove webhook in message {msg.id}: message already deleted.")
        #     return

        if webhook_deleted:
            await msg.channel.send(ALERT_MESSAGE_TEMPLATE.format(user=msg.author.mention))
            delete_state = "The webhook was successfully deleted."
        else:
            delete_state = "There was an error when deleting the webhook, it might have already been removed."
        message = (
            f"{format_user(msg.author)} posted a Discord webhook URL to {msg.channel.mention}. {delete_state} "
            f"Webhook URL was `{redacted_url}`"
        )
        log.debug(message)

        # Send entry to moderation alerts.
        # await self.mod_log.send_log_message(
        #     icon_url=Icons.token_removed,
        #     colour=Colour(Colours.soft_red),
        #     title="Discord webhook URL removed!",
        #     text=message,
        #     thumbnail=msg.author.display_avatar.url,
        #     channel_id=Channels.mod_alerts
        # )

    @Cog.listener()
    async def on_message(self, msg: Message) -> None:
        """Check if a Discord webhook URL is in `message`."""
        # Ignore DMs; can't delete messages in there anyway.
        if not msg.guild or msg.author.bot:
            return
        if msg.guild.id not in WHITELIST:
            return

        matches = WEBHOOK_URL_RE.search(msg.content)
        if matches:
            async with self.bot.http_session.delete(matches[0]) as resp:
                # The Discord API Returns a 204 NO CONTENT response on success.
                deleted_successfully = resp.status == 204
            await self.delete_and_respond(msg, matches[1] + "xxx", webhook_deleted=deleted_successfully)

    @Cog.listener()
    async def on_message_edit(self, before: Message, after: Message) -> None:
        """Check if a Discord webhook URL is in the edited message `after`."""
        await self.on_message(after)


def setup(bot: Bot) -> None:
    """Load `WebhookRemover` cog."""
    bot.add_cog(WebhookRemover(bot))
