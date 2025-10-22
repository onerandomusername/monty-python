import enum
from collections.abc import Callable
from typing import Annotated, ClassVar, Literal

import disnake
import pydantic
import yarl
from disnake.ext import commands
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings as PydanticBaseSettings
from pydantic_settings import SettingsConfigDict


__all__ = (  # noqa: RUF022
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


class BaseSettings(PydanticBaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def is_url(url: str) -> str:
    try:
        result = yarl.URL(url)
    except Exception:
        msg = "Invalid URL"
        raise ValueError(msg) from None
    if not all([result.scheme in ("http", "https"), result.host is not None]):
        msg = "Invalid URL"
        raise ValueError(msg)
    return url


StrHttpUrl = Annotated[str, pydantic.AfterValidator(is_url)]


class ClientCls(BaseSettings):
    name: ClassVar[str] = "Monty Python"
    token: str = Field(validation_alias="BOT_TOKEN")
    default_command_prefix: str = Field("-", validation_alias="PREFIX")
    config_prefix: ClassVar[str] = "monty-python"
    intents: ClassVar[disnake.Intents] = disnake.Intents.default() | disnake.Intents.message_content
    command_sync_flags: ClassVar[commands.CommandSyncFlags] = commands.CommandSyncFlags(
        allow_command_deletion=False,
        sync_guild_commands=True,
        sync_global_commands=True,
        sync_commands_debug=True,
        sync_on_cog_actions=True,
    )
    allowed_mentions: ClassVar[disnake.AllowedMentions] = disnake.AllowedMentions(
        everyone=False,
        roles=False,
        users=False,
        replied_user=True,
    )
    # debug configuration
    debug: bool = Field(False, validation_alias="BOT_DEBUG")
    proxy: str | None = Field(None, validation_alias="BOT_PROXY_URL")
    test_guilds: Annotated[
        list[int] | None,
        Field(
            description="The list of IDs of the guilds where you're going to test your application commands.",
            validation_alias="TEST_GUILDS",
        ),
    ] = None
    extensions: set[str] | bool | None = Field(None, validation_alias="BOT_EXTENSIONS")

    @field_validator("extensions", mode="before")
    @classmethod
    def parse_extensions(cls, v: str | None) -> set[str] | bool | None:
        """Parse BOT_EXTENSIONS environment variable into a set of strings."""
        if v is None or v == "":
            return None
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        return {ext.strip() for ext in v.split(",") if ext.strip()}

    # source and support
    git_sha: str | None = Field(None, validation_alias="GIT_SHA")
    git_repo: ClassVar[StrHttpUrl] = "https://github.com/onerandomusername/monty-python"
    support_server: ClassVar[str] = "mPscM4FjWB"
    # note that these are the default invite permissions,
    # But Monty fetches the ones configured in the developer portal and replace these
    default_invite_permissions: ClassVar[disnake.Permissions] = disnake.Permissions(
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

    @property
    def git_ref(self) -> str:
        """Return the git reference to use in URLs."""
        return self.git_sha or "main"

    @property
    def activity(self) -> disnake.Game:
        """Return the bot's activity based on debug status."""
        return disnake.Game(name=f"Commands: {self.default_command_prefix}help")


class DatabaseCls(BaseSettings):
    postgres_bind: pydantic.PostgresDsn = Field(validation_alias="DB_BIND")
    run_migrations: bool = Field(True, validation_alias="DB_RUN_MIGRATIONS")
    migration_target: str = Field("head", validation_alias="DB_MIGRATION_TARGET")


class RedisCls(BaseSettings):
    uri: pydantic.RedisDsn = Field(validation_alias="REDIS_URI", default=pydantic.RedisDsn("redis://redis:6379"))
    use_fakeredis: bool = Field(validation_alias="USE_FAKEREDIS", default=False)
    prefix: ClassVar[str] = ClientCls.config_prefix + ":"


class MonitoringCls(BaseSettings):
    """Runtime monitoring configuration exposed via environment variables.

    The individual fields keep the original environment variable names via
    Field(..., validation_alias=...)
    """

    debug_logging: bool = Field(True, validation_alias="LOG_DEBUG")
    sentry_enabled: bool = Field(False, validation_alias="SENTRY_DSN")
    trace_loggers: str | None = Field(None, validation_alias="BOT_TRACE_LOGGERS")
    bot_log_mode: str = Field("dev", validation_alias="BOT_LOG_MODE")

    public_status_page: str | None = Field(None, validation_alias="UPTIME_STATUS_PAGE")
    ping_url: StrHttpUrl | None = Field(None, validation_alias="UPTIME_URL")
    ping_interval: int = Field(60, validation_alias="UPTIME_INTERVAL")

    @property
    def log_mode(self) -> Literal["daily", "dev"]:
        """Return the log mode based on bot_log_mode."""
        return "daily" if (self.bot_log_mode or "").lower() == "daily" else "dev"

    ping_query_params: ClassVar[dict[str, str | Callable[[commands.Bot], str]]] = {
        "status": "up",
        "msg": "OK",
        "ping": lambda bot: f"{bot.latency * 1000:.2f}",
    }

    @field_validator("sentry_enabled", mode="before")
    @classmethod
    def parse_sentry_enabled(cls, v: str | None) -> bool:
        """Parse SENTRY_ENABLED environment variable into a boolean."""
        return not (v is None or v == "")


class StatsCls(BaseSettings):
    host: str = Field("localhost", validation_alias="STATS_HOST")
    port: int = Field(8125, validation_alias="STATS_PORT")
    prefix: str = Field(ClientCls.config_prefix)


class AuthCls(BaseSettings):
    github: str | None = Field(None, validation_alias="GITHUB_TOKEN")
    snekbox: str | None = Field(None, validation_alias="SNEKBOX_AUTH")


class EndpointsCls(BaseSettings):
    pypi_simple: ClassVar[StrHttpUrl] = "https://pypi.org/simple/"
    app_info: StrHttpUrl | None = Field(None, validation_alias="APPLICATION_INFO_ENDPOINT")
    top_pypi_packages: StrHttpUrl | None = Field(None, validation_alias="PYPI_TOP_PACKAGES")

    snekbox: StrHttpUrl | None = Field(None, validation_alias="SNEKBOX_URL")

    black_formatter: StrHttpUrl | None = Field(None, validation_alias="BLACK_API")
    black_playground: StrHttpUrl = Field("https://black.vercel.app/", validation_alias="BLACK_PLAYGROUND")

    paste_service: StrHttpUrl | None = Field(None, validation_alias="PASTE_SERVICE")
    raw_paste: StrHttpUrl | None = Field(None, validation_alias="PASTE_SERVICE_RAW")


# DEPRECATED: to be moved to a postgres value
# note: enablement of Codeblock actions is controlled via the Feature.CODEBLOCK_RECOMMENDATIONS
class CodeBlockCls(BaseModel):
    cooldown_seconds: int = 300
    minimum_lines: int = 4


# TODO: every colour across the bot should use colours from this palette
# this includes calling disnake.Colour.blurple() and other methods.
# TODO: redesign colour palette
class ColoursCls(BaseModel):
    white: int = 0xFFFFFF
    blue: int = 0x0279FD
    bright_green: int = 0x01D277
    dark_green: int = 0x1F8B4C
    orange: int = 0xE67E22
    pink: int = 0xCF84E0
    purple: int = 0xB734EB
    soft_green: int = 0x68C290
    soft_orange: int = 0xF9CB54
    soft_red: int = 0xCD6D6D
    yellow: int = 0xF9F586
    python_blue: int = 0x4B8BBE
    python_yellow: int = 0xFFD43B
    grass_green: int = 0x66FF00
    gold: int = 0xE6C200


## DEPRECATED
# TODO: Will be replaced in favour of application emojis
class EmojisCls(BaseModel):
    cross_mark: str = "\u274c"
    star: str = "\u2b50"
    christmas_tree: str = "\U0001f384"
    check: str = "\u2611"
    envelope: str = "\U0001f4e8"
    trashcan: str = Field("<:trashcan:637136429717389331>", validation_alias="TRASHCAN_EMOJI")
    trashcan_on_red: str = Field("<:trashcan:976669056587415592>", validation_alias="TRASHCAN_ON_RED_EMOJI")
    trashcat_special: str = Field("<:catborked:976598820651679794>", validation_alias="TRASHCAT_SPECIAL_EMOJI")
    ok_hand: str = ":ok_hand:"
    hand_raised: str = "\U0001f64b"
    black: str = "<:black_format:928530654143066143>"
    upload: str = "\U0001f4dd"
    snekbox: str = "\U0001f40d"

    # GitHub octicons
    discussion_answered: str = "<:discussion_answered:979267343710584894>"
    issue_open: str = "<:issue_open:882464248951877682>"
    issue_closed: str = "<:issue_closed:882464248972865536>"
    issue_closed_completed: str = "<:issue_closed_completed:979047130847117343>"
    issue_closed_unplanned: str = "<:issue_closed_unplanned:979052245507276840>"
    issue_draft: str = "<:issue_draft:882464249337774130>"
    pull_request_open: str = "<:pull_open:882464248721182842>"
    pull_request_closed: str = "<:pull_closed:882464248989638676>"
    pull_request_draft: str = "<:pull_draft:882464249065136138>"
    pull_request_merged: str = "<:pull_merged:882464249119645787>"

    number_emojis: dict[int, str] = {
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

    confirmation: str = "\u2705"
    decline: str = "\u274c"
    no_choice_light: str = "\u25fb\ufe0f"

    x: str = "\U0001f1fd"
    o: str = "\U0001f1f4"

    stackoverflow_tag: str = "<:stackoverflow_tag:882722838161797181>"
    stackoverflow_views: str = "<:stackoverflow_views:882722838006607922>"

    reddit_upvote: str = "<:reddit_upvote:882722837868195901>"
    reddit_comments: str = "<:reddit_comments:882722838153416705>"


# TODO: stash all icons as emojis
class IconsCls(BaseModel):
    questionmark: str = "https://cdn.discordapp.com/emojis/512367613339369475.png"
    bookmark: str = "https://cdn.discordapp.com/emojis/654080405988966419.png?width=20&height=20"
    github_avatar_url: str = "https://avatars1.githubusercontent.com/u/9919"
    python_discourse: str = "https://global.discourse-cdn.com/business6/uploads/python1/optimized/1X/4c06143de7870c35963b818b15b395092a434991_2_180x180.png"


## Feature Management
class Feature(enum.Enum):
    CODEBLOCK_RECOMMENDATIONS = "PYTHON_CODEBLOCK_RECOMMENDATIONS"
    DISCORD_TOKEN_REMOVER = "DISCORD_BOT_TOKEN_FILTER"  # noqa: S105
    DISCORD_WEBHOOK_REMOVER = "DISCORD_WEBHOOK_FILTER"
    GITHUB_COMMENT_LINKS = "GITHUB_EXPAND_COMMENT_LINKS"
    GITHUB_DISCUSSIONS = "GITHUB_AUTOLINK_DISCUSSIONS"
    GITHUB_ISSUE_EXPAND = "GITHUB_AUTOLINK_ISSUE_SHOW_DESCRIPTION"
    GITHUB_ISSUE_LINKS = "GITHUB_EXPAND_ISSUE_LINKS"
    GLOBAL_SOURCE = "GLOBAL_SOURCE_COMMAND"
    INLINE_DOCS = "INLINE_DOCUMENTATION"
    INLINE_EVALULATION = "INLINE_EVALULATION"
    PYPI_AUTOCOMPLETE = "PYPI_PACKAGE_AUTOCOMPLETE"
    PYTHON_DISCOURSE_AUTOLINK = "PYTHON_DISCOURSE_AUTOLINK"
    RUFF_RULE_V2 = "RUFF_RULE_V2"
    SOURCE_AUTOCOMPLETE = "META_SOURCE_COMMAND_AUTOCOMPLETE"


# legacy implementation of features, will be removed in the future
class GuildsCls(BaseModel):
    disnake: int = 808030843078836254
    nextcord: int = 881118111967883295


## compatibility with configuration before pydantic. Replace the definitions
# with themselves and have global instances.
# theoretically temporary
Client = ClientCls()  # pyright: ignore[reportCallIssue]
Database = DatabaseCls()  # pyright: ignore[reportCallIssue]
Redis = RedisCls()
Stats = StatsCls()  # pyright: ignore[reportCallIssue]
Auth = AuthCls()  # pyright: ignore[reportCallIssue]
Endpoints = EndpointsCls()  # pyright: ignore[reportCallIssue]
Monitoring = MonitoringCls()  # pyright: ignore[reportCallIssue]
CodeBlock = CodeBlockCls()
Colours = ColoursCls()
Emojis = EmojisCls()  # pyright: ignore[reportCallIssue]
Icons = IconsCls()
Guilds = GuildsCls()
