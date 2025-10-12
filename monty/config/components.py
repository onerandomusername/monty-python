from typing import cast

import disnake

from monty.config.models import Category, CategoryMetadata


__all__ = ("get_category_choices",)


def get_category_choices() -> list[disnake.OptionChoice]:
    """Get a list of category choices for use in slash command options."""
    options = []
    for cat in Category:
        metadata: CategoryMetadata = cat.value
        default_name = (
            metadata.autocomplete_text
            if isinstance(metadata.autocomplete_text, str)
            else (metadata.autocomplete_text.get("_") or metadata.name)
        )
        assert isinstance(default_name, str)
        localised: disnake.Localized | str
        if isinstance(metadata.autocomplete_text, dict):
            data = metadata.autocomplete_text.copy()
            data.pop("_", default_name)
            data = cast("dict[disnake.Locale, str]", data)
            for opt, val in data.items():
                data[opt] = str(metadata.emoji) + " " + val
            localised = disnake.Localized(
                string=default_name,
                data=data,
            )
        else:
            localised = str(metadata.emoji) + " " + default_name
        options.append(disnake.OptionChoice(name=localised, value=cat.name))
    return options
