from __future__ import annotations

import functools
import logging
import re
import typing

import disnake
from disnake.ext import commands

from monty.bot import Monty
from monty.constants import Client
from monty.utils import responses


if typing.TYPE_CHECKING:
    AnyContext = typing.Union[commands.Context, disnake.Interaction]

logger = logging.getLogger(__name__)


ERROR_COLOUR = responses.DEFAULT_FAILURE_COLOUR

ERROR_TITLE_REGEX = re.compile(r"((?<=[a-z])[A-Z]|(?<=[a-zA-Z])[A-Z](?=[a-z]))")


class ErrorHandler(commands.Cog, name="Error Handler"):
    """Handles all errors across the bot."""

    def __init__(self, bot: Monty):
        self.bot = bot

    @staticmethod
    def error_embed(title: str, message: str) -> disnake.Embed:
        """Create an error embed with an error colour and reason and return it."""
        return disnake.Embed(title=title, description=message, colour=ERROR_COLOUR)

    @staticmethod
    def get_title_from_name(error: typing.Union[Exception, str]) -> str:
        """
        Return a message dervived from the exception class name.

        Eg NSFWChannelRequired returns NSFW Channel Required
        """
        if not isinstance(error, str):
            error = error.__class__.__name__
        return re.sub(ERROR_TITLE_REGEX, r" \1", error)

    @staticmethod
    def _reset_command_cooldown(ctx: AnyContext) -> bool:
        if return_value := ctx.command.is_on_cooldown(ctx):
            ctx.command.reset_cooldown(ctx)
        return return_value

    async def handle_user_input_error(
        self,
        ctx: AnyContext,
        error: commands.UserInputError,
        reset_cooldown: bool = True,
    ) -> disnake.Embed:
        """Handling deferred from main error handler to handle UserInputErrors."""
        if reset_cooldown:
            self._reset_command_cooldown(ctx)
        msg = None
        if isinstance(error, commands.BadUnionArgument):
            msg = self.get_title_from_name(str(error))
        title = self.get_title_from_name(error)
        return self.error_embed(title, msg or str(error))

    async def handle_bot_missing_perms(self, ctx: AnyContext, error: commands.BotMissingPermissions) -> None:
        """Handles bot missing permissing by dming the user if they have a permission which may be able to fix this."""  # noqa: E501
        embed = self.error_embed("Permissions Failure", str(error))
        bot_perms = ctx.channel.permissions_for(ctx.me)
        not_responded = True  # noqa: F841
        if bot_perms >= disnake.Permissions(send_messages=True, embed_links=True):
            await ctx.send(embeds=[embed])
            not_responded = False  # noqa: F841
        elif bot_perms >= disnake.Permissions(send_messages=True):
            # make a message as similar to the embed, using as few permissions as possible
            # this is the only place we send a standard message instead of an embed
            # so no helper methods are necessary
            await ctx.send(
                "**Permissions Failure**\n\n" "I am missing the permissions required to properly execute your command."
            )
            # intentionally not setting responded to True, since we want to attempt to dm the user
            logger.warning(
                f"Missing partial required permissions for {ctx.channel}. "
                "I am able to send messages, but not embeds."
            )
        else:
            logger.error(f"Unable to send an error message to channel {ctx.channel}")

    async def handle_check_failure(
        self, ctx: AnyContext, error: commands.CheckFailure
    ) -> typing.Optional[disnake.Embed]:
        """Handle CheckFailures seperately given that there are many of them."""
        title = "Check Failure"
        if isinstance(error, commands.CheckAnyFailure):
            title = self.get_title_from_name(error.checks[-1])
        elif isinstance(error, commands.PrivateMessageOnly):
            title = "DMs Only"
        elif isinstance(error, commands.NoPrivateMessage):
            title = "Server Only"
        elif isinstance(error, commands.NotOwner):
            # hide errors for owner check failures
            return None
        elif isinstance(error, commands.BotMissingPermissions):
            # defer handling BotMissingPermissions to a method
            # the error could be that the bot is unable to send messages, which would cause
            # the error handling to fail
            await self.handle_bot_missing_perms(ctx, error)
            return None
        else:
            title = self.get_title_from_name(error)
        embed = self.error_embed(title, str(error))
        return embed

    async def on_command_error(self, ctx: AnyContext, error: commands.CommandError) -> None:
        """Activates when a command raises an error."""
        if getattr(error, "handled", False):
            logging.debug(f"Command {ctx.command} had its error already handled locally, ignoring.")
            return

        if isinstance(error, commands.CommandNotFound):
            # ignore every time the user inputs a message that starts with our prefix but isn't a command
            # this will be modified in the future to support prefilled commands
            return

        embed: typing.Optional[disnake.Embed] = None
        should_respond = True

        if isinstance(error, commands.UserInputError):
            embed = await self.handle_user_input_error(ctx, error)
        elif isinstance(error, commands.CheckFailure):
            embed = await self.handle_check_failure(ctx, error)
            # handle_check_failure may send its own error if its a BotMissingPermissions error.
            if embed is None:
                should_respond = False
        elif isinstance(error, commands.ConversionError):
            error = error.original
        elif isinstance(error, commands.DisabledCommand):
            logger.debug("")
            if ctx.command.hidden:
                should_respond = False
            else:
                msg = f"Command `{ctx.invoked_with}` is disabled."
                if reason := ctx.command.extras.get("disabled_reason", None):
                    msg += f"\nReason: {reason}"
                embed = self.error_embed("Command Disabled", msg)

        elif isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, disnake.Forbidden):
                logger.warn(f"Permissions error occurred in {ctx.command}.")
                await self.handle_bot_missing_perms(ctx, error.original)
                should_respond = False
            else:
                # todo: this should properly handle plugin errors and note that they are not bot bugs
                # todo: this should log somewhere else since this is a bot bug.
                # generic error
                logger.error("Error occurred in command or message component", exc_info=error.original)
                # built in command msg
                title = "Internal Error"
                error_str = str(error.original).replace("``", "`\u200b`")
                msg = (
                    "Something went wrong internally in the action you were trying to execute. "
                    "Please report this error and the code below and what you were trying to do in "
                    f"the [support server](https://discord.gg/{Client.support_server})."
                    f"\n\n``{error_str}``"
                )

                embed = self.error_embed(title, msg)

        # TODO: this has a fundamental problem with any BotMissingPermissions error
        # if the issue is the bot does not have permissions to send embeds or send messages...
        # yeah, problematic.

        if not should_respond:
            logger.debug(
                "Not responding to error since should_respond is falsey because either "
                "the embed has already been sent or belongs to a hidden command and thus should be hidden."
            )
            return

        if embed is None:
            embed = self.error_embed(self.get_title_from_name(error), str(error))

        await ctx.send(embeds=[embed])

    @commands.Cog.listener(name="on_command_error")
    @commands.Cog.listener(name="on_slash_command_error")
    @commands.Cog.listener(name="on_message_command_error")
    async def on_error(self, ctx: AnyContext, error: Exception) -> None:
        """Handle all errors with one mega error handler."""
        if isinstance(ctx, disnake.Interaction):
            if ctx.response.is_done():
                ctx.send = functools.partial(ctx.followup.send, ephemeral=True)
            else:
                ctx.send = functools.partial(ctx.send, ephemeral=True)

            if isinstance(
                ctx,
                (
                    disnake.ApplicationCommandInteraction,
                    disnake.MessageCommandInteraction,
                    disnake.UserCommandInteraction,
                ),
            ):
                ctx.command = ctx.application_command
            elif isinstance(ctx, (disnake.MessageInteraction, disnake.ModalInteraction)):
                # todo: this is a hack, but it works for now
                ctx.command = ctx.message
            else:
                # i don't even care, this code should be unreachable but its also the error handler
                ctx.command = ctx
        try:
            await self.on_command_error(ctx, error)
        except Exception as e:
            logger.exception("Error occurred in error handler", exc_info=e)


def setup(bot: Monty) -> None:
    """Add the error handler to the bot."""
    bot.add_cog(ErrorHandler(bot))
