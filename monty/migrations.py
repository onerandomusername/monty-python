import os

import alembic.command
import alembic.config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import monty.alembic
from monty import constants


def run_upgrade(connection: Connection, cfg: alembic.config.Config) -> None:
    """Run alembic upgrades."""
    cfg.attributes["connection"] = connection
    alembic.command.upgrade(cfg, "head")


async def run_async_upgrade(engine: AsyncEngine) -> None:
    """Run alembic upgrades but async."""
    alembic_cfg = alembic.config.Config()
    alembic_cfg.set_main_option("script_location", os.path.dirname(monty.alembic.__file__))  # noqa: PTH120
    async with engine.connect() as conn:
        await conn.run_sync(run_upgrade, alembic_cfg)


async def run_alembic(engine: AsyncEngine | None = None) -> None:
    """Run alembic migrations."""
    engine = engine or create_async_engine(constants.Database.postgres_bind)
    await run_async_upgrade(engine)
