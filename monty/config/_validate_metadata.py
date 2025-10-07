from monty import constants
from monty.config.models import Category, ConfigAttrMetadata, SelectOptionMetadata


__all__ = ()


def _check_config_metadata(metadata: dict[str, ConfigAttrMetadata]) -> None:
    for m in metadata.values():
        assert 0 < len(m.description) < 100
        assert m.button or m.select_option
        if m.select_option:
            assert isinstance(m.select_option, SelectOptionMetadata)
            assert m.type is bool
        if m.depends_on_features:
            for feature in m.depends_on_features:
                assert feature in constants.Feature
    for c in Category:
        if not any(c in m.categories for m in metadata.values()):
            raise ValueError(f"Category {c} has no associated config attributes")
