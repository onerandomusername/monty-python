import io
import re
from base64 import b64encode

import discord
from discord.ext import commands
from bot.bot import Bot
from bot.constants import CloudAHK

DISCORD_UPLOAD_LIMIT = 8000000  # 8 MB


class RunnableCodeConverter(commands.Converter):
    async def convert(self, ctx, code:str):
        if code.startswith("https://p.ahkscript.org/"):
            url = code.replace("?p=", "?r=")
            async with ctx.http.get(url) as resp:
                if resp.status == 200 and str(resp.url) == url:
                    code = await resp.text()
                else:
                    raise commands.CommandError("Failed fetching code from pastebin.")

        return code


class Eval(commands.Cog):
    """Run python code through a online sandbox."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def cloudahk_call(self, ctx, code, lang="ahk"):
        """Call to CloudAHK to run "code" written in "lang". Replies to invoking user with stdout/runtime of code."""

        token = "{0}:{1}".format(CloudAHK.user, CloudAHK.password)

        encoded = b64encode(bytes(token, "utf-8")).decode("utf-8")
        headers = {"Authorization": "Basic " + encoded}

        # remove first line with backticks and highlighting lang
        if re.match("^```.*\n", code):
            code = code[code.find("\n") + 1 :]

        # strip backticks on both sides
        code = code.strip("`").strip()

        url = f"{CloudAHK.url}/{lang}/run"

        # set code to run python
        code = "#!/usr/bin/env python3\n" + code
        # call cloudahk with 20 in timeout
        async with self.bot.http_session.post(url, data=code, headers=headers, timeout=20) as resp:
            if resp.status == 200:
                result = await resp.json()
            else:
                raise commands.CommandError("Something went wrong.")

        stdout, time = result["stdout"].strip(), result["time"]

        file = None
        stdout = stdout.replace("\r", "")

        if time is None:
            resp = "Program ran for too long and was aborted."
        else:
            stdout_len = len(stdout)
            display_time = f"Runtime: `{time:.2f}` seconds"

            if stdout_len < 1800 and stdout.count("\n") < 20:
                # upload as plaintext
                stdout = stdout.replace("``", "`\u200b`")

                resp = "```py\n{0}\n```{1}".format(stdout if stdout else "No output.", display_time)

            elif stdout_len < DISCORD_UPLOAD_LIMIT:
                fp = io.BytesIO(bytes(stdout.encode("utf-8")))
                file = discord.File(fp, "output.txt")
                resp = f"Output dumped to file.\n{display_time}"

            else:
                raise commands.CommandError("Output greater than 8 MB.")

        # logging for security purposes and checking for abuse
        # filename = "ahk_eval/{0}_{1}_{2}_{3}".format(ctx.guild.id, ctx.author.id, ctx.message.id, lang)
        # with open(filename, "w", encoding="utf-8-sig") as f:
        #     f.write(
        #         "{0}\n\nLANG: {1}\n\nCODE:\n{2}\n\nPROCESSING TIME: {3}\n\nSTDOUT:\n{4}\n".format(
        #             ctx.stamp, lang, code, time, stdout
        #         )
        #     )

        reference = ctx.message.to_reference()
        reference.fail_if_not_exists = False
        await ctx.send(content=resp, file=file, reference=reference)

    @commands.command(aliases=('e',))
    @commands.cooldown(rate=1, per=5.0, type=commands.BucketType.user)
    async def eval(self, ctx, *, code: RunnableCodeConverter):
        """Run python code in a sandboxed environment."""

        await self.cloudahk_call(ctx, code)

def setup(bot):
	bot.add_cog(Eval(bot))