import inspect
from pathlib import Path
from typing import Optional, Tuple, Union
from urllib.parse import urldefrag

import disnake
from disnake import Embed
from disnake.ext import commands

from monty.bot import Bot
from monty.constants import Client, Source
from monty.utils.converters import SourceConverter, SourceType
from monty.utils.helpers import encode_github_link
from monty.utils.messages import DeleteView


class BotSource(commands.Cog):
    """Displays information about the bot's source code."""

    @commands.command(name="source", aliases=("src",))
    async def source_command(
        self,
        ctx: Union[commands.Context, disnake.ApplicationCommandInteraction],
        *,
        source_item: SourceConverter = None,
    ) -> None:
        """Display information and a GitHub link to the source code of a command or cog."""

        async def send_message(embed: disnake.Embed, components: list = None) -> None:
            if isinstance(ctx, commands.Context):
                view = DeleteView(ctx.author, initial_message=ctx.message)
            else:
                view = DeleteView(ctx.author)
            if components:
                view.children.extend(components)
            await ctx.send(embed=embed, view=view)
            return

        if not source_item:
            embed = Embed(title=f"{Client.name}'s GitHub Repository")
            embed.add_field(name="Repository", value=f"[Go to GitHub]({Source.github})")
            embed.set_thumbnail(url=Source.github_avatar_url)
            await send_message(embed)
            return

        embed, url = self.build_embed(source_item)
        components = [disnake.ui.Button(url=url, label="Open Github")]

        custom_id = encode_github_link(url)
        if frag := (urldefrag(url)[1]):
            frag = frag.replace("#", "").replace("L", "")
            num1, num2 = frag.split("-")
            if int(num2) - int(num1) < 30:
                components.append(
                    disnake.ui.Button(style=disnake.ButtonStyle.blurple, label="Expand", custom_id=custom_id)
                )

        await send_message(embed, components=components)

    @commands.slash_command(name="source")
    async def source_slash_command(self, inter: disnake.ApplicationCommandInteraction, item: str = None) -> None:
        """Get the source of my commands and cogs."""
        if item is not None:
            try:
                item = await SourceConverter().convert(inter, item)
            except commands.BadArgument as e:
                await inter.response.send_message(str(e), ephemeral=True)
                return
        await self.source_command(inter, source_item=item)

    def get_source_link(self, source_item: SourceType) -> Tuple[str, str, Optional[int]]:
        """
        Build GitHub link of source item, return this link, file location and first line number.

        Raise BadArgument if `source_item` is a dynamically-created object (e.g. via internal eval).
        """
        if isinstance(
            source_item,
            (
                commands.InvokableSlashCommand,
                commands.SubCommandGroup,
                commands.SubCommand,
                commands.InvokableUserCommand,
                commands.InvokableMessageCommand,
            ),
        ):
            meth = inspect.unwrap(source_item.callback)
            src = meth.__code__
            filename = src.co_filename
        elif isinstance(source_item, commands.Command):
            callback = inspect.unwrap(source_item.callback)
            src = callback.__code__
            filename = src.co_filename
        else:
            src = type(source_item)
            try:
                filename = inspect.getsourcefile(src)
            except TypeError:
                raise commands.BadArgument("Cannot get source for a dynamically-created object.")

        if not isinstance(source_item, str):
            try:
                lines, first_line_no = inspect.getsourcelines(src)
            except OSError:
                raise commands.BadArgument("Cannot get source for a dynamically-created object.")

            lines_extension = f"#L{first_line_no}-L{first_line_no+len(lines)-1}"
        else:
            first_line_no = None
            lines_extension = ""

        file_location = Path(filename).relative_to(Path.cwd()).as_posix()

        url = f"{Source.github}/blob/main/{file_location}{lines_extension}"

        return url, file_location, first_line_no or None

    def build_embed(self, source_object: SourceType) -> Optional[Tuple[Embed, str]]:
        """Build embed based on source object."""
        url, location, first_line = self.get_source_link(source_object)

        if isinstance(source_object, commands.Command):
            description = source_object.short_doc
            title = f"Command: {source_object.qualified_name}"
        elif isinstance(source_object, commands.InvokableSlashCommand):
            title = f"Slash Command: {source_object.qualified_name}"
            description = source_object.description
        elif isinstance(source_object, commands.SubCommandGroup):
            title = f"Slash Sub Command Group: {source_object.qualified_name}"
            description = inspect.cleandoc(source_object.callback.__doc__).split("\n", 1)[0]
        elif isinstance(source_object, commands.SubCommand):
            title = f"Slash Sub-Command: {source_object.qualified_name}"
            description = source_object.option.description
        elif isinstance(source_object, commands.InvokableUserCommand):
            title = f"User Command: {source_object.qualified_name}"
            description = inspect.cleandoc(source_object.callback.__doc__).split("\n", 1)[0]
        elif isinstance(source_object, commands.InvokableMessageCommand):
            title = f"Message Command: {source_object.qualified_name}"
            description = inspect.cleandoc(source_object.callback.__doc__).split("\n", 1)[0]
        else:
            title = f"Cog: {source_object.qualified_name}"
            description = source_object.description.splitlines()[0]

        embed = Embed(title=title, description=description)
        embed.set_thumbnail(url=Source.github_avatar_url)
        embed.add_field(name="Source Code", value=f"[Go to GitHub]({url})")
        line_text = f":{first_line}" if first_line else ""
        embed.set_footer(text=f"{location}{line_text}")

        return embed, url


def setup(bot: Bot) -> None:
    """Load the BotSource cog."""
    bot.add_cog(BotSource())
