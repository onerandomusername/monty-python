import logging
from os import environ
from typing import NamedTuple

import disnake
import yarl


__all__ = (
    "Client",
    "CloudAHK",
    "Colours",
    "Emojis",
    "Icons",
    "Stats",
    "Tokens",
    "RedisConfig",
    "Wolfram",
    "RedirectOutput",
    "ERROR_REPLIES",
    "NEGATIVE_REPLIES",
    "POSITIVE_REPLIES",
)

log = logging.getLogger(__name__)


class Client(NamedTuple):

    name = "Monty Python"
    config_prefix = "monty-python"
    version = environ.get("GIT_SHA", "development")
    prefix = environ.get("PREFIX", "-")
    token = environ.get("BOT_TOKEN")
    debug = environ.get("BOT_DEBUG", "true").lower() == "true"
    github_bot_repo = "https://github.com/onerandomusername/monty-python"
    trace_loggers = environ.get("BOT_TRACE_LOGGERS")
    extensions = environ.get("BOT_EXTENSIONS", None) and {
        ext.strip() for ext in environ.get("BOT_EXTENSIONS").split(",")
    }
    support_server = "mPscM4FjWB"
    invite_permissions = disnake.Permissions(
        view_audit_log=True,
        read_messages=True,
        send_messages=True,
        send_messages_in_threads=True,
        manage_messages=True,
        embed_links=True,
        attach_files=True,
        read_message_history=True,
        add_reactions=True,
        use_external_emojis=True,
        use_external_stickers=True,
    )


DEBUG_MODE = Client.debug


class Database:
    auth_token = environ.get("CONFIG_AUTH")
    url = yarl.URL(environ.get("CONFIG_ROOT"))


class CloudAHK:
    url = environ.get("CLOUDAHK_URL", None)
    user = environ.get("CLOUDAHK_USER", None)
    password = environ.get("CLOUDAHK_PASS", None)


class CodeBlock:
    channel_whitelist: list[int] = []
    cooldown_channels: list[int] = []
    cooldown_seconds: int = 300
    minimum_lines: int = 4


class Colours:
    white = 0xFFFFFF
    blue = 0x0279FD
    bright_green = 0x01D277
    dark_green = 0x1F8B4C
    orange = 0xE67E22
    pink = 0xCF84E0
    purple = 0xB734EB
    soft_green = 0x68C290
    soft_orange = 0xF9CB54
    soft_red = 0xCD6D6D
    yellow = 0xF9F586
    python_blue = 0x4B8BBE
    python_yellow = 0xFFD43B
    grass_green = 0x66FF00
    gold = 0xE6C200


class Emojis:
    cross_mark = "\u274C"
    star = "\u2B50"
    christmas_tree = "\U0001F384"
    check = "\u2611"
    envelope = "\U0001F4E8"
    trashcan = environ.get("TRASHCAN_EMOJI", "<:trashcan:637136429717389331>")
    ok_hand = ":ok_hand:"
    hand_raised = "\U0001F64B"
    black = "<:black_format:928530654143066143>"
    upload = "\U0001f4dd"
    snekbox = "\U0001f40d"

    # These icons are from Github's repo https://github.com/primer/octicons/
    issue_open = "<:issue_open:882464248951877682>"
    issue_closed = "<:issue_closed:882464248972865536>"
    issue_draft = "<:issue_draft:882464249337774130>"  # Not currently used by Github, but here for future.
    pull_request_open = "<:pull_open:882464248721182842>"
    pull_request_closed = "<:pull_closed:882464248989638676>"
    pull_request_draft = "<:pull_draft:882464249065136138>"
    pull_request_merged = "<:pull_merged:882464249119645787>"

    number_emojis = {
        1: "\u0031\ufe0f\u20e3",
        2: "\u0032\ufe0f\u20e3",
        3: "\u0033\ufe0f\u20e3",
        4: "\u0034\ufe0f\u20e3",
        5: "\u0035\ufe0f\u20e3",
        6: "\u0036\ufe0f\u20e3",
        7: "\u0037\ufe0f\u20e3",
        8: "\u0038\ufe0f\u20e3",
        9: "\u0039\ufe0f\u20e3",
    }

    confirmation = "\u2705"
    decline = "\u274c"

    x = "\U0001f1fd"
    o = "\U0001f1f4"

    stackoverflow_tag = "<:stackoverflow_tag:882722838161797181>"
    stackoverflow_views = "<:stackoverflow_views:882722838006607922>"

    reddit_upvote = "<:reddit_upvote:882722837868195901>"
    reddit_comments = "<:reddit_comments:882722838153416705>"


class Endpoints:
    app_info = environ.get("APPLICATION_INFO_ENDPOINT")


class Guilds:
    disnake = 808030843078836254
    modmail = 798235512208490526
    nextcord = 881118111967883295
    cat_dev_group = 808854246119178250
    dexp = 798235585130266654
    gurkult = 789192517375623228
    testing = 789603028382122014
    branding = 928111022085144636


class Icons:
    questionmark = "https://cdn.discordapp.com/emojis/512367613339369475.png"
    bookmark = (
        "https://images-ext-2.discordapp.net/external/zl4oDwcmxUILY7sD9ZWE2fU5R7n6QcxEmPYSE5eddbg/"
        "%3Fv%3D1/https/cdn.discordapp.com/emojis/654080405988966419.png?width=20&height=20"
    )


class URLs:
    paste_service = environ.get("PASTE_SERVICE")
    snekbox_api = environ.get("SNEKBOX_URL")
    snekbox_auth = environ.get("SNEKBOX_AUTH")
    black_formatter = environ.get("BLACK_API")
    black_playground = environ.get("BLACK_PLAYGROUND", "https://black.vercel.app/")


class Paste:
    raw_paste_endpoint: str = environ.get("PASTE_SERVICE_RAW", "")


class Stats(NamedTuple):
    host = environ.get("STATS_HOST", "localhost")
    port = int(environ.get("STATS_PORT", 8125))
    prefix = Client.config_prefix


class Tokens(NamedTuple):
    github = environ.get("GITHUB_TOKEN")


class RedisConfig(NamedTuple):
    host = environ.get("REDIS_HOST", "redis")
    port = environ.get("REDIS_PORT", 6379)
    password = environ.get("REDIS_PASSWORD")
    use_fakeredis = environ.get("USE_FAKEREDIS", "false").lower() == "true"
    prefix = Client.config_prefix


class Wolfram(NamedTuple):
    user_limit_day = int(environ.get("WOLFRAM_USER_LIMIT_DAY", 10))
    guild_limit_day = int(environ.get("WOLFRAM_GUILD_LIMIT_DAY", 67))
    key = environ.get("WOLFRAM_API_KEY")


class Source:
    github = Client.github_bot_repo
    github_avatar_url = "https://avatars1.githubusercontent.com/u/9919"


class RedirectOutput:
    delete_delay: int = 10


GIT_SHA = environ.get("GIT_SHA", "foobar")

# Bot replies
ERROR_REPLIES = [
    "Please don't do that.",
    "You have to stop.",
    "Do you mind?",
    "In the future, don't do that.",
    "That was a mistake.",
    "You blew it.",
    "You're bad at computers.",
    "Are you trying to kill me?",
    "Noooooo!!",
    "I can't believe you've done this",
]

NEGATIVE_REPLIES = [
    "Noooooo!!",
    "Nope.",
    "I'm sorry Dave, I'm afraid I can't do that.",
    "I don't think so.",
    "Not gonna happen.",
    "Out of the question.",
    "Huh? No.",
    "Nah.",
    "Naw.",
    "Not likely.",
    "No way, José.",
    "Not in a million years.",
    "Fat chance.",
    "Certainly not.",
    "NEGATORY.",
    "Nuh-uh.",
    "Not in my house!",
]

POSITIVE_REPLIES = [
    "Yep.",
    "Absolutely!",
    "Can do!",
    "Affirmative!",
    "Yeah okay.",
    "Sure.",
    "Sure thing!",
    "You're the boss!",
    "Okay.",
    "No problem.",
    "I got you.",
    "Alright.",
    "You got it!",
    "ROGER THAT",
    "Of course!",
    "Aye aye, cap'n!",
    "I'll allow it.",
]
