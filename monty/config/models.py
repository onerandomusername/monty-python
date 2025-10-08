import enum
from dataclasses import InitVar, dataclass, field
from typing import Callable, Coroutine, Literal, Optional, Type, Union

import disnake
from disnake import Locale

from monty import constants


Localised = Union[str, dict[Locale | Literal["_"], str]]


@dataclass(kw_only=True, frozen=True)
class StatusMessages:
    set_attr_success: str = (  # this also can take an `old_setting` parameter
        "Successfully set `{name}`  to ``{new_setting}``."
    )
    set_attr_fail: str = "Could not change `{name}`: {err}"
    view_attr_success: str = "`{name}` is currently set to ``{current_setting}``."
    view_attr_success_unset: str = "`{name}` is currently unset."  # will take a current_setting parameter if needed
    clear_attr_success: str = "`{name}` has successfully been reset."
    clear_attr_success_with_default: str = "The `{name}` setting has been reset to ``{default}``."


@dataclass(kw_only=True, frozen=True)
class CategoryButtonMetadata:
    label: Localised
    style: disnake.ButtonStyle = disnake.ButtonStyle.grey


@dataclass(kw_only=True, frozen=True)
class CategoryMetadata:
    name: Localised
    description: Localised
    emoji: disnake.PartialEmoji | str
    button: CategoryButtonMetadata
    autocomplete_text: Localised


class Category(enum.Enum):
    General = CategoryMetadata(
        name="General",
        description="General bot configuration options.",
        emoji="⚙️",
        button=CategoryButtonMetadata(
            label="Edit General",
        ),
        autocomplete_text="General bot configuration",
    )
    GitHub = CategoryMetadata(
        name="GitHub Configuration",
        description="Configuration options for GitHub related features.",
        emoji="🐙",
        button=CategoryButtonMetadata(
            label="Edit Github",
        ),
        autocomplete_text="GitHub Configuration",
    )
    # Python = CategoryMetadata(
    #     name="Python",
    #     description="Configuration options for Python related features.",
    #     emoji="🐍",
    #     button=CategoryButtonMetadata(
    #         label="Edit Python",
    #     ),
    #     autocomplete_text="Python tools",
    # )


### for select components


@dataclass(kw_only=True, frozen=True)
class SelectMetadata:
    supertext: Localised | None = None
    description: Localised
    placeholder: Localised
    subtext: Localised | None = None


class SelectGroup(enum.Enum):
    GITHUB_EXPANSIONS = SelectMetadata(
        supertext="GitHub Expansions",
        description="Options for automatically expanding GitHub links, such as issues and specific lines in files.",
        placeholder="Select GitHub expansions to enable",
        subtext="Select none to disable all GitHub expansions.",
    )


@dataclass(kw_only=True, frozen=True)
class SelectOptionMetadata:
    group: SelectGroup
    description: Localised | None = None


### for free response options


@dataclass(kw_only=True, frozen=True)
class FreeResponseMetadata:
    button_label: Localised
    button_style: Callable[..., disnake.ButtonStyle] = lambda _: disnake.ButtonStyle.green
    text_input_style: disnake.TextInputStyle = disnake.TextInputStyle.short
    min_length: int = 1
    max_length: int = 4000
    placeholder: Optional[Localised] = None


@dataclass(kw_only=True, frozen=True)
class ConfigAttrMetadata:
    name: Localised
    description: Localised
    nullable: bool = True
    type: Union[Type[str], Type[int], Type[float], Type[bool]]
    emoji: disnake.PartialEmoji | str | None = None
    category: InitVar[Category | None] = None
    categories: set[Category] | frozenset[Category] = field(default_factory=frozenset)
    select_option: Optional[SelectOptionMetadata] = None
    modal: Optional[FreeResponseMetadata] = None
    requires_bot: bool = False
    long_description: Optional[str] = None
    depends_on_features: Optional[tuple[constants.Feature]] = None
    validator: Optional[Union[Callable, Callable[..., Coroutine]]] = None
    status_messages: StatusMessages = field(default_factory=StatusMessages)

    def __post_init__(self, category: Category | None) -> None:
        if not category and not self.categories:
            raise ValueError("Either category or categories must be provided")
        if category and self.categories:
            raise ValueError("Only one of category or categories can be provided")
        object.__setattr__(self, "categories", self.categories or frozenset({category}))

        if self.type not in (str, int, float, bool):
            raise ValueError("type must be one of str, int, float, or bool")
        if len(self.name) > 45:
            raise ValueError("name must be less than 45 characters")
        if len(self.description) > 100:
            raise ValueError("description must be less than 100 characters")

    def get_select_option(
        self,
        *,
        locale: Locale | None = None,
        attr: str,
        default: bool = False,
    ) -> disnake.SelectOption:
        """Return a select option for this metadata, localised if needed."""
        if not self.select_option:
            raise ValueError("This ConfigAttrMetadata does not have select_option metadata")
        description = self.select_option.description
        key = locale or "_"
        name = self.name
        if isinstance(name, dict):
            name = name.get(key) or name.get("_") or "Option"

        if isinstance(description, dict):
            description = description.get(key) or description.get("_") or None
        return disnake.SelectOption(
            label=name,
            value=attr,
            default=default,
            emoji=self.emoji,
            description=description,
        )

    def get_button(self, *, locale: Locale | None = None) -> disnake.ui.Button:
        """Return the button for this metadata, localised if needed."""
        if not self.modal:
            raise ValueError("This ConfigAttrMetadata does not have modal metadata")
        label = self.modal.button_label
        key = locale or "_"
        if isinstance(label, dict):
            label = label.get(key) or label.get("_") or "Edit"
        return disnake.ui.Button(label=label, style=self.modal.button_style(None))

    def get_text_input(
        self,
        *,
        locale: Locale | None = None,
        current: str | None = None,
        name: str,
        custom_id: str,
    ) -> disnake.ui.TextInput:
        """Return the text input for this metadata, localised if needed."""
        if not self.modal:
            raise ValueError("This ConfigAttrMetadata does not have modal metadata")
        placeholder = self.description
        key = locale or "_"
        if isinstance(placeholder, dict):
            placeholder = placeholder.get(key) or placeholder.get("_") or None
        return disnake.ui.TextInput(
            label=name,
            style=self.modal.text_input_style,
            min_length=self.modal.min_length,
            max_length=self.modal.max_length,
            placeholder=placeholder,
            value=current or None,
            required=not self.nullable,
            custom_id=custom_id,
        )
