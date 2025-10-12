import dataclasses
import logging
from os import environ
from typing import TYPE_CHECKING, Literal, cast

import disnake


if TYPE_CHECKING:
    from monty.log import MontyLogger

__all__ = (
    "Client",
    "Monitoring",
    "Database",
    "Redis",
    "CodeBlock",
    "Colours",
    "Emojis",
    "Icons",
    "Auth",
    "Endpoints",
    "Feature",
    "Guilds",
)

# due to recursive imports, we have to use this
log = cast("MontyLogger", logging.getLogger(__name__))


class Client:
    name = "Monty Python"
    token = environ.get("BOT_TOKEN")
    version = environ.get("GIT_SHA", "main")
    default_command_prefix = environ.get("PREFIX", "-")
    config_prefix = "monty-python"

    # debug configuration
    debug = environ.get("BOT_DEBUG", "true").lower() == "true"
    proxy = environ.get("BOT_PROXY_URL", "") or None
    extensions: bool | set[str] = (
        "BOT_EXTENSIONS" in environ and {ext.strip() for ext in environ["BOT_EXTENSIONS"].split(",")}
    ) or "BOT_EXTENSIONS" in environ
    # source and support
    git_repo = "https://github.com/onerandomusername/monty-python"
    support_server = "mPscM4FjWB"
    # note that these are the default invite permissions,
    # But Monty fetches the ones configured in the developer portal and replace these
    default_invite_permissions = disnake.Permissions(
        view_channel=True,
        send_messages=True,
        send_messages_in_threads=True,
        manage_messages=True,
        manage_threads=True,
        embed_links=True,
        attach_files=True,
        read_message_history=True,
        add_reactions=True,
        use_external_emojis=True,
        # these are enabled for future features, but not currently used
        change_nickname=True,
        create_public_threads=True,
        create_private_threads=True,
        view_audit_log=True,
    )


class Database:
    postgres_bind: str = environ.get("DB_BIND", "")
    run_migrations: bool = not (environ.get("DB_RUN_MIGRATIONS", "true").lower() == "false")
    migration_target: str = environ.get("DB_MIGRATION_TARGET", "head")


class Redis:
    uri = environ.get("REDIS_URI", "redis://redis:6379")
    use_fakeredis = environ.get("USE_FAKEREDIS", "false").lower() == "true"
    prefix = Client.config_prefix + ":"


class Monitoring:
    debug_logging = environ.get("LOG_DEBUG", "true").lower() == "true"
    sentry_enabled = bool(environ.get("SENTRY_DSN"))
    trace_loggers = environ.get("BOT_TRACE_LOGGERS")
    log_mode: Literal["daily", "dev"] = "daily" if "daily" == environ.get("BOT_LOG_MODE", "dev").lower() else "dev"

    public_status_page: str | None = environ.get("UPTIME_STATUS_PAGE") or None
    ping_url: str = environ.get("UPTIME_URL", "")
    ping_interval: int = int(environ.get("UPTIME_INTERVAL", 60))  # in seconds
    ping_enabled: bool = bool(ping_url)
    ping_query_params = {
        "status": "up",
        "msg": "OK",
        "ping": lambda bot: f"{bot.latency * 1000:.2f}",
    }


class Stats:
    host = environ.get("STATS_HOST", "localhost")
    port = int(environ.get("STATS_PORT", 8125))
    prefix = Client.config_prefix


# DEPRECATED: to be moved to a postgres value
# note: enablement of Codeblock actions is controlled via the Feature.CODEBLOCK_RECOMMENDATIONS
class CodeBlock:
    cooldown_seconds: int = 300
    minimum_lines: int = 4


# TODO: every colour across the bot should use colours from this palette
# this includes calling disnake.Colour.blurple() and other methods.
# TODO: redesign colour palette
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


## DEPRECATED
# TODO: Will be replaced in favour of application emojis
class Emojis:
    cross_mark = "\u274c"
    star = "\u2b50"
    christmas_tree = "\U0001f384"
    check = "\u2611"
    envelope = "\U0001f4e8"
    trashcan = environ.get("TRASHCAN_EMOJI", "<:trashcan:637136429717389331>")
    trashcan_on_red = environ.get("TRASHCAN_ON_RED_EMOJI", "<:trashcan:976669056587415592>")
    trashcat_special = environ.get("TRASHCAT_SPECIAL_EMOJI", "<:catborked:976598820651679794>")
    ok_hand = ":ok_hand:"
    hand_raised = "\U0001f64b"
    black = "<:black_format:928530654143066143>"
    upload = "\U0001f4dd"
    snekbox = "\U0001f40d"

    # These icons are from Github's repo https://github.com/primer/octicons/
    discussion_answered = "<:discussion_answered:979267343710584894>"
    issue_open = "<:issue_open:882464248951877682>"
    issue_closed = "<:issue_closed:882464248972865536>"
    issue_closed_completed = "<:issue_closed_completed:979047130847117343>"
    issue_closed_unplanned = "<:issue_closed_unplanned:979052245507276840>"
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
    no_choice_light = "\u25fb\ufe0f"

    x = "\U0001f1fd"
    o = "\U0001f1f4"

    stackoverflow_tag = "<:stackoverflow_tag:882722838161797181>"
    stackoverflow_views = "<:stackoverflow_views:882722838006607922>"

    reddit_upvote = "<:reddit_upvote:882722837868195901>"
    reddit_comments = "<:reddit_comments:882722838153416705>"


# TODO: stash all icons as emojis
class Icons:
    questionmark = "https://cdn.discordapp.com/emojis/512367613339369475.png"
    bookmark = (
        "https://images-ext-2.discordapp.net/external/zl4oDwcmxUILY7sD9ZWE2fU5R7n6QcxEmPYSE5eddbg/"
        "%3Fv%3D1/https/cdn.discordapp.com/emojis/654080405988966419.png?width=20&height=20"
    )
    github_avatar_url = "https://avatars1.githubusercontent.com/u/9919"
    python_discourse = "https://global.discourse-cdn.com/business6/uploads/python1/optimized/1X/4c06143de7870c35963b818b15b395092a434991_2_180x180.png"  # noqa: E501


## Authentication and Endpoint management for external services


class Auth:
    github = environ.get("GITHUB_TOKEN")
    github_secondary = environ.get("GITHUB_TOKEN_SECONDARY")
    snekbox = environ.get("SNEKBOX_AUTH")


class Endpoints:
    app_info = environ.get("APPLICATION_INFO_ENDPOINT")
    pypi_simple = "https://pypi.org/simple/"
    top_pypi_packages = environ.get("PYPI_TOP_PACKAGES", "")

    snekbox = environ.get("SNEKBOX_URL", "")

    black_formatter = environ.get("BLACK_API")
    black_playground = environ.get("BLACK_PLAYGROUND", "https://black.vercel.app/")

    paste_service = environ.get("PASTE_SERVICE", "")
    raw_paste: str = environ.get("PASTE_SERVICE_RAW", "")


## Feature Management
@dataclasses.dataclass()
class Feature:
    CODEBLOCK_RECOMMENDATIONS: str = "PYTHON_CODEBLOCK_RECOMMENDATIONS"
    DISCORD_TOKEN_REMOVER: str = "DISCORD_BOT_TOKEN_FILTER"  # noqa: S105
    DISCORD_WEBHOOK_REMOVER: str = "DISCORD_WEBHOOK_FILTER"
    GITHUB_COMMENT_LINKS: str = "GITHUB_EXPAND_COMMENT_LINKS"
    GITHUB_DISCUSSIONS: str = "GITHUB_AUTOLINK_DISCUSSIONS"
    GITHUB_ISSUE_EXPAND: str = "GITHUB_AUTOLINK_ISSUE_SHOW_DESCRIPTION"
    GITHUB_ISSUE_LINKS: str = "GITHUB_EXPAND_ISSUE_LINKS"
    GLOBAL_SOURCE: str = "GLOBAL_SOURCE_COMMAND"
    INLINE_DOCS: str = "INLINE_DOCUMENTATION"
    INLINE_EVALULATION: str = "INLINE_EVALULATION"
    PYPI_AUTOCOMPLETE: str = "PYPI_PACKAGE_AUTOCOMPLETE"
    PYTHON_DISCOURSE_AUTOLINK: str = "PYTHON_DISCOURSE_AUTOLINK"
    RUFF_RULE_V2: str = "RUFF_RULE_V2"
    SOURCE_AUTOCOMPLETE: str = "META_SOURCE_COMMAND_AUTOCOMPLETE"


# legacy implementation of features, will be removed in the future
class Guilds:
    disnake = 808030843078836254
    nextcord = 881118111967883295
