from databases import Database
from ormar import ModelMeta
from sqlalchemy import MetaData

from monty import constants


database = Database(constants.Database.postgres_bind)
metadata = MetaData()


class BaseMeta(ModelMeta):
    """Base Metadata class, as all models use the same metadata."""

    metadata = metadata
    database = database
