import functools
import importlib
import logging
import textwrap
from collections.abc import Iterable, Sequence
from typing import Any, Protocol, TypeGuard, cast

import disnake
from disnake import ApplicationInstallTypes, InteractionContextTypes
from disnake.ext import commands

from monty.utils.extensions import EXTENSIONS, walk_extensions


DOCS_DIR = "docs/commands"
"""Directory to write the generated command docs to."""

PREFIX_COMMANDS_FILE = f"{DOCS_DIR}/prefix-commands.md"
APP_COMMANDS_FILE = f"{DOCS_DIR}/app-commands.md"

COG_SETTING_ATTR = {
    disnake.ApplicationCommandType.chat_input: "__cog_slash_settings__",
    disnake.ApplicationCommandType.user: "__cog_user_settings__",
    disnake.ApplicationCommandType.message: "__cog_message_settings__",
}


class AppCommandLike(Protocol):
    """Simplified app command protocol."""

    qualified_name: str
    description: str | None
    body: disnake.ApplicationCommand | None
    contexts: InteractionContextTypes
    install_types: ApplicationInstallTypes
    cog: commands.Cog | None
    parent: Any | None


def pretty_print_options(options: Iterable[disnake.Option] | None, indent: int = 0) -> str:
    """
    Format slash command options into markdown.

    Returns a markdown fragment describing the options, choices and
    any constraints. Returns an empty string if there are no options.
    """
    if not options:
        return ""

    lines: list[str] = []
    prefix = "  " * indent

    for opt in options:
        line = f"{prefix}- `{opt.name}`"
        tname = opt.type.name
        if tname:
            line += f" (`{tname}`)"
        if opt.required:
            line += " (required)"
        lines.append(line)

        if (desc := opt.description) and desc != "-":
            lines.append(f"{prefix}  {desc}")

        if choices := opt.choices:
            choice_strs = [f"`{c.name}` (`{c.value}`)" for c in choices]
            lines.append(f"{prefix}  Choices: {', '.join(choice_strs)}")

        constraints: list[str] = []
        if opt.min_value is not None:
            constraints.append(f"Min: `{opt.min_value}`")
        if opt.max_value is not None:
            constraints.append(f"Max: `{opt.max_value}`")
        if opt.min_length is not None:
            constraints.append(f"Min length: `{opt.min_length}`")
        if opt.max_length is not None:
            constraints.append(f"Max length: `{opt.max_length}`")
        if constraints:
            lines.append(f"\n{prefix}  Constraints: {', '.join(constraints)}")

        if opt.options:
            lines.append(f"{prefix}  Sub-options:")
            lines.append(pretty_print_options(opt.options, indent + 2))

    return "\n".join(lines) + "\n\n"


def pretty_print_prefix_command(command: commands.Command) -> str:
    """
    Format a prefix command into a markdown section.

    Includes the signature, short description and aliases if present.
    """
    lines = []

    params = []
    for name, param in command.clean_params.items():
        if param.default is not param.empty:
            params.append(f"[{name}={param.default}]")
        elif param.kind == param.VAR_POSITIONAL:
            params.append(f"[{name}...]")
        else:
            params.append(f"<{name}>")
    signature = f"{command.qualified_name} {' '.join(params)}".strip()
    lines.append(f"### `{signature}`")

    short_doc = command.short_doc or command.help or "No details provided"
    lines.append(f"*{short_doc}*")

    alias_list = []
    for a in command.aliases:
        if not command.parent:
            alias_list.append(f"`{a}`")
        else:
            alias_list.append(f"`{command.full_parent_name} {a}`")
    root_aliases = getattr(command, "root_aliases", ())
    alias_list.extend([f"`{a}`" for a in root_aliases])
    alias_list = sorted(alias_list)
    if alias_list:
        lines.extend(["", "", f"**Can also use:** {', '.join(alias_list)}"])

    return "\n".join(lines) + "\n\n"


def _extract_member_names(value: Any, enum_cls: type) -> list[str]:
    """
    Return the matching enum member names (lowercased) for a bitmask value.

    Works with both flag-style enums (bitmasks) and normal enums.
    """
    value = getattr(value, "value", None)
    if not isinstance(value, int):
        return []

    names: list[str] = []
    members = getattr(enum_cls, "__members__", None)

    if members is None:
        try:
            members = list(enum_cls)  # pyright: ignore[reportArgumentType]
        except Exception:
            return []

    iterator = members.items() if isinstance(members, dict) else members
    for item in iterator:
        member = item[1] if isinstance(members, dict) else item
        member_val = getattr(member, "value", None)
        member_name = getattr(member, "name", None)

        if member_val is None or member_name is None:
            continue

        if (member_val & value) == member_val:
            names.append(member_name.lower())

    return names or [str(getattr(value, "name", value)).lower()]


def _format_enum_flags(value: Any, enum_cls: type) -> list[str]:
    """Format enum/flag values into a list of canonical member strings."""
    if not isinstance(value, enum_cls):
        return []

    names = _extract_member_names(value, enum_cls)

    if not names:
        try:
            member_name = getattr(value, "name", None)
            if member_name:
                names = [member_name.lower()]
        except Exception:
            pass

    return names or [str(getattr(value, "name", value)).lower()]


def _flag_names_from_value(value: disnake.flags.BaseFlags | None, enum_cls: type) -> list[str]:
    """
    Convert a Disnake flag/enum value into human-friendly names.

    Handles a few Disnake-specific enums specially, otherwise delegates to
    the generic formatter.
    """
    if value is None:
        return []

    if isinstance(value, (InteractionContextTypes, ApplicationInstallTypes)):
        names: list[str] = []
        if isinstance(value, InteractionContextTypes):
            if value.guild:
                names.append("Guilds")
            if value.bot_dm:
                names.append("Bot DMs")
            if value.private_channel:
                names.append("Private Channels")

        if isinstance(value, ApplicationInstallTypes):
            if value.guild:
                names.append("Guild")
            if value.user:
                names.append("User")

        return names

    return _format_enum_flags(value, enum_cls)


def _get_attr(command: Any, attr_name: str) -> Any:
    """Get attribute from command or from command.body as a fallback."""
    return getattr(command, attr_name, None) or getattr(getattr(command, "body", None), attr_name, None)


def _resolve_command_flags(
    command: Any,
    enum_cls: type,
    attr_name: str,
    cog_class: type[commands.Cog],
) -> list[str]:
    """
    Resolve and format the human-friendly names for a command flag attribute.

    This will look on the command, fall back to parents, then consult cog
    defaults before returning a conservative fallback.
    """
    value = _get_attr(command, attr_name)
    names = _flag_names_from_value(value, enum_cls)

    if not names:
        parent = getattr(command, "parent", None)
        while parent is not None and not names:
            parent_value = _get_attr(parent, attr_name)
            names = _flag_names_from_value(parent_value, enum_cls)
            parent = parent.parent

    if not names and cog_class is not None:
        cmd_body = command.body
        settings_attr = None
        if cmd_body is not None:
            cmd_type = getattr(cmd_body, "type", None)
            if cmd_type is not None:
                settings_attr = COG_SETTING_ATTR.get(cmd_type)
        if settings_attr:
            settings = getattr(cog_class, settings_attr, None)
            if settings:
                try:
                    val = settings.get(attr_name) if isinstance(settings, dict) else getattr(settings, attr_name, None)
                except Exception:
                    val = None

                if val is not None:
                    names = _flag_names_from_value(val, enum_cls)

    if not names:
        names = _flag_names_from_value(enum_cls.all(), enum_cls)

    if enum_cls in (InteractionContextTypes, ApplicationInstallTypes):
        return names

    return [n.replace("_", " ").title() for n in names]


def pretty_print_app_command(
    command: commands.InvokableApplicationCommand | AppCommandLike, cog_class: type[commands.Cog]
) -> str:
    """Format an application (slash/user/message) command into markdown."""
    lines = [f"### `{command.qualified_name}`"]

    if options := getattr(command.body, "options", None):
        options_str = pretty_print_options(options)
        if options_str:
            lines.append(options_str)

    if desc := getattr(command, "description", None):
        lines.append(desc)
        lines.append("")

    context_names = _resolve_command_flags(command, InteractionContextTypes, "contexts", cog_class=cog_class)
    lines.append(f"**Usable in:** {', '.join(f'`{n}`' for n in context_names)}")
    lines.append("")

    install_names = _resolve_command_flags(command, ApplicationInstallTypes, "install_types", cog_class=cog_class)
    lines.append(f"**Installable as:** {', '.join(f'`{n}`' for n in install_names)}")
    lines.append("")

    return "\n".join(lines) + "\n\n"


def _find_cog_classes() -> list[tuple[str, str, type[commands.Cog]]]:
    """Import extensions and return a list of (name, doc, class) tuples for cogs."""
    cogs: list[tuple[str, str, type[commands.Cog]]] = []

    EXTENSIONS.update(dict(walk_extensions()))

    for ext, meta in EXTENSIONS.items():
        if not meta.has_cog:
            continue

        try:
            mod = importlib.import_module(ext)
        except ImportError:
            continue

        for item_name in dir(mod):
            obj = getattr(mod, item_name)
            if isinstance(obj, type) and issubclass(obj, commands.Cog) and obj.__doc__ is not None:
                cog_name = getattr(obj, "__cog_name__", obj.__name__)
                cogs.append((cog_name, textwrap.dedent(obj.__doc__), obj))

    cogs.sort(key=lambda item: item[0].lower())
    return cogs


def _gather_prefix_commands(cog_class: type[commands.Cog]) -> list[commands.Command]:
    """Return visible prefix commands defined on a cog class, sorted."""
    try:
        commands_list = list(commands.Cog.walk_commands(cog_class))  # pyright: ignore[reportArgumentType]

        visible = [c for c in commands_list if not c.hidden]
        visible.sort(key=lambda c: c.qualified_name.lower())
        return visible

    except Exception as exc:
        logging.getLogger(__name__).warning(f"Failed to collect prefix commands from {cog_class.__name__}: {exc}")
        return []


def _contains_subcommands(
    command: commands.InvokableApplicationCommand,
) -> TypeGuard[commands.SubCommand | commands.SubCommandGroup]:
    """Return True if the application command has subcommands/options groups."""
    body = command.body
    options = getattr(body, "options", None)

    if not options:
        return False

    for option in options:
        option_type = str(getattr(option, "type", "")).lower()
        if any(sub_type in option_type for sub_type in ("sub_command", "sub_command_group")):
            return True

    return False


def _build_subcommand(command: Any, option: Any) -> AppCommandLike:
    """Return a lightweight object representing a subcommand for rendering."""
    from types import SimpleNamespace

    sub_body = SimpleNamespace(options=option.options or [])

    app = SimpleNamespace(
        name=option.name,
        qualified_name=f"{getattr(command, 'qualified_name', getattr(command, 'name', ''))} {option.name}",
        description=option.description,
        body=sub_body,
        install_types=getattr(command, "install_types", None),
        contexts=getattr(option, "contexts", None) or getattr(command, "contexts", None),
        hidden=False,
        cog=command.cog,
        parent=command,
    )
    return cast("AppCommandLike", app)


def _gather_app_commands(cog_class: type[commands.Cog]) -> list[commands.InvokableApplicationCommand | AppCommandLike]:
    """
    Return application commands defined on a cog, expanding subcommands.

    We accept classes here since Disnake's API expects an instance; passing
    the class works for discovery.
    """
    try:
        commands_list = list(cog_class.get_application_commands(cog_class))  # pyright: ignore[reportArgumentType]
        app_commands: list[commands.InvokableApplicationCommand | AppCommandLike] = []

        for command in commands_list:
            if _contains_subcommands(command):
                body = command.body
                options = body.options or []

                for option in options:
                    option_type = str(option.type).lower()
                    if not any(sub_type in option_type for sub_type in ("sub_command", "sub_command_group")):
                        continue

                    sub_cmd = _build_subcommand(command, option)
                    app_commands.append(sub_cmd)
            elif isinstance(command, (commands.SubCommand, commands.SubCommandGroup)):
                continue
            else:
                app_commands.append(command)

            app_commands.sort(key=lambda cmd: cmd.qualified_name.lower())
        return app_commands

    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to collect app commands from %s", cog_class.__name__, exc_info=exc)
        return []


def _save_markdown(content: str, filepath: str) -> None:
    """Save markdown to disk and log errors."""
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)


def autodoc_extensions() -> None:
    """Generate documentation for commands."""
    prefix_content = "# Prefix Commands\n\n"
    app_content = "# App Commands\n\n"

    cogs = _find_cog_classes()

    for cog_name, doc, cog_class in cogs:

        def _render_cog_section(
            commands_list: Sequence[commands.InvokableApplicationCommand | AppCommandLike | commands.Command],
            render_fn: Any,
            cog_name: str = cog_name,
            doc: str = doc,
        ) -> str:
            if not commands_list:
                return ""
            blocks = [render_fn(cmd) for cmd in commands_list]
            return f"## {cog_name}\n\n{doc}\n\n" + "".join(blocks) + "\n"

        prefix_commands = _gather_prefix_commands(cog_class)
        prefix_content += _render_cog_section(prefix_commands, pretty_print_prefix_command)

        app_commands = _gather_app_commands(cog_class)
        app_content += _render_cog_section(
            app_commands, functools.partial(pretty_print_app_command, cog_class=cog_class)
        )

    _save_markdown(prefix_content, PREFIX_COMMANDS_FILE)
    _save_markdown(app_content, APP_COMMANDS_FILE)


if __name__ == "__main__":
    logging.getLogger("markdown_it").setLevel(logging.WARNING)
    logging.getLogger("monty").setLevel(logging.WARNING)
    autodoc_extensions()
    logging.getLogger(__name__).info("[autodoc] Generation complete.")
