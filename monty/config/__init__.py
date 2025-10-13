from monty.config._validate_metadata import _check_config_metadata
from monty.config.components import get_category_choices
from monty.config.metadata import CATEGORY_TO_ATTR, GROUP_TO_ATTR, METADATA
from monty.config.models import Category, ConfigAttrMetadata, FreeResponseMetadata, SelectGroup, SelectOptionMetadata


__all__ = (
    "CATEGORY_TO_ATTR",
    "GROUP_TO_ATTR",
    "METADATA",
    "Category",
    "ConfigAttrMetadata",
    "FreeResponseMetadata",
    "SelectGroup",
    "SelectOptionMetadata",
    "get_category_choices",
)

_check_config_metadata(METADATA)

del _check_config_metadata
