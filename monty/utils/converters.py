from typing import Union

import disnake
from disnake.ext import commands


class WrappedMessageConverter(commands.MessageConverter):
    """A converter that handles embed-suppressed links like <http://example.com>."""

    async def convert(self, ctx: commands.Context, argument: str) -> disnake.Message:
        """Wrap the commands.MessageConverter to handle <> delimited message links."""
        # It's possible to wrap a message in [<>] as well, and it's supported because its easy
        if argument.startswith("[") and argument.endswith("]"):
            argument = argument[1:-1]
        if argument.startswith("<") and argument.endswith(">"):
            argument = argument[1:-1]

        return await super().convert(ctx, argument)


SourceType = Union[
    commands.Command,
    commands.Cog,
    commands.InvokableSlashCommand,
    commands.SubCommand,
    commands.SubCommandGroup,
]


class SourceConverter(commands.Converter):
    """Convert an argument into a command or cog."""

    @staticmethod
    async def convert(ctx: commands.Context, argument: str) -> SourceType:
        """Convert argument into source object."""
        cog = ctx.bot.get_cog(argument)
        if cog:
            return cog

        cmd = ctx.bot.get_slash_command(argument)
        if cmd:
            if not cmd.guild_ids:
                return cmd
            elif ctx.guild and ctx.guild.id in cmd.guild_ids:
                return cmd

        cmd = ctx.bot.get_command(argument)
        if cmd:
            return cmd

        # attempt to get the context menu command

        cmd = ctx.bot.get_message_command(argument)
        if cmd:
            if not cmd.guild_ids:
                return cmd
            elif ctx.guild and ctx.guild.id in cmd.guild_ids:
                return cmd

        cmd = ctx.bot.get_user_command(argument)
        if cmd:
            if not cmd.guild_ids:
                return cmd
            elif ctx.guild and ctx.guild.id in cmd.guild_ids:
                return cmd

        raise commands.BadArgument(f"Unable to convert `{argument}` to valid command, application command, or Cog.")
