"""
Schema defintions for configuration models.

Each configuration option needs a renderable. At this moment is either a select menu or a text input.
Each configuration needs to specify when it is available, the installation contexts, and the categories it belongs to.
A configuration option can belong to multiple categories.

Each configuration option can have a validator of both sync and async types. The async type is only run when the
user is attempting to set the value, and is not run when loading the configuration from the database.

For settable contexts, we're reusing discord's InstallationContexts for this,
as per-user configuration is done on a per-user basis.

Each option can additionally specify a description, which is shown in the UI.

Finally, there is a button configuration option, which can be configured for the modal that will be launched.

### How does someone use this??

/config category?:x -> Message with buttons for each category, and a button to go back to this menu.

category page: show 8 options per page, with pagination if needed. Each option includes either
a button to launch a modal, or a select menu to change the value in-line.

It seems basic. Some toggeable options such as multiple choice options can be done in-line,
but free-response options need a modal to be launched.

It is also possible to have a select menu for some boolean options, such as grouping all of the
GitHub expansion options into one multiple choice select menu.
"""

import enum
from typing import Callable

import disnake
import pydantic


class CategoryName(enum.Enum):
    GENERAL = "General"
    PYTHON = "Python"
    GITHUB = "GitHub"


class Category(pydantic.BaseModel):
    name: CategoryName
    description: str
    emoji: disnake.PartialEmoji
    colour: disnake.Colour | None = None


class ConfigOptionMetadata(pydantic.BaseModel):
    name: str
    description: str | None = None
    installation_contexts: list[disnake.InstallationContext]
    categories: list[CategoryName]
    renderable: type[disnake.ui.Select | disnake.ui.TextInput]
    button_label: str | None = None
    button_style: Callable[..., ..., disnake.ButtonStyle] | None = None
    """Function that returns a ButtonStyle, given the current value. This allows for toggle buttons."""
    emoji: disnake.PartialEmoji | None = None
    """Emoji to use for the button that launches the modal or select menu."""
    validator: pydantic.Validator | None = None
    async_validator: Callable | None = None


CONFIG_OPTIONS: list[ConfigOptionMetadata] = []
