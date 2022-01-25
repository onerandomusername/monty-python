import disnake
from disnake.ext import commands
from disnake.ext.commands import LargeInt, Range

from monty.bot import Monty


class DevTools(commands.Cog):
    """Command for inviting a bot."""

    def __init__(self, bot: Monty):
        self.bot = bot

    @commands.slash_command()
    async def invite(
        self,
        inter: disnake.AppCmdInter,
        client_id: LargeInt,
        permissions: Range[-1, disnake.Permissions.all().value] = None,
        guild: str = None,
        include_applications_commands: bool = True,
        raw_link: bool = False,
        ephemeral: bool = True,
    ) -> None:
        """
        [BETA] Generate an invite to add a bot to a guild. NOTE: may not work on all bots.

        Parameters
        ----------
        client_id: ID of the user to invite
        permissions: Value of permissions to pre-fill with
        guild: ID of the guild to pre-fill the invite.
        include_applications_commands: Whether or not to include the applications.commands scope.
        raw_link: Instead of a fancy button, I'll give you the raw link.
        ephemeral: Whether or not to send an ephemeral response.
        """
        if client_id:
            try:
                client_id = int(client_id)
            except (TypeError, ValueError):
                await inter.response.send_message("client id must be an integer.", ephemeral=True)
                return
        else:
            client_id = inter.bot.user.id

        if permissions:
            permissions = disnake.Permissions(permissions)
        elif client_id == inter.bot.user.id:
            # todo: make this a constant
            permissions = disnake.Permissions(412317248704)
        else:
            permissions = disnake.Permissions(-1)

        if guild is not None:
            try:
                guild = disnake.Object(guild)
            except TypeError:
                await inter.response.send_message("Guild ID must be an integer.", ephemeral=True)
                return
        else:
            guild = disnake.utils.MISSING

        # validated all of the input, now see if client_id exists
        try:
            user = inter.bot.get_user(client_id) or await inter.bot.fetch_user(client_id)
        except disnake.NotFound:
            await inter.send("Sorry, that user does not exist.", ephemeral=True)
            return

        if not user.bot:
            await inter.send("Sorry, that user is not a bot.", ephemeral=True)

        scopes = ("bot", "applications.commands") if include_applications_commands else ("bot",)
        url = disnake.utils.oauth_url(
            client_id,
            permissions=permissions,
            guild=guild,
            scopes=scopes,
        )
        message = " ".join(
            [
                "Click below to invite" if not raw_link else "Click the following link to invite",
                "me" if client_id == inter.bot.user.id else user.mention,
                "to the specified guild!" if guild else "to your guild!",
            ]
        )
        if raw_link:
            message += f"\n{url}"
            components = disnake.utils.MISSING
        else:
            components = disnake.ui.Button(
                url=url, style=disnake.ButtonStyle.link, label=f"Click to invite {user.name}!"
            )

        await inter.response.send_message(
            message,
            allowed_mentions=disnake.AllowedMentions.none(),
            components=components,
            ephemeral=ephemeral,
        )

    @invite.error
    async def invite_error(self, inter: disnake.CommandInteraction, error: Exception) -> None:
        """Handle errors in the invite command."""
        if isinstance(error, commands.ConversionError):
            if isinstance(error.original, ValueError):
                await inter.send("Client ID must be an integer.", ephemeral=True)
                error.handled = True


def setup(bot: Monty) -> None:
    """Add the devtools cog to the bot."""
    bot.add_cog(DevTools(bot))
