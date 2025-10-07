from monty.config._validate_metadata import _check_config_metadata
from monty.config.components import get_category_choices
from monty.config.metadata import METADATA
from monty.config.models import ButtonMetadata, Category, ConfigAttrMetadata, SelectGroup, SelectOptionMetadata


__all__ = (
    "METADATA",
    "Category",
    "ConfigAttrMetadata",
    "SelectGroup",
    "ButtonMetadata",
    "SelectOptionMetadata",
    "get_category_choices",
)

_check_config_metadata(METADATA)

del _check_config_metadata
