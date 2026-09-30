from logging.config import fileConfig

from alembic import context

# Imported for its side effect: the models register themselves on Base.metadata, which is
# what autogenerate compares the database against.
import app.database.models  # noqa: F401
from app.config import get_settings
from app.database.database import Base, UtcDateTime, engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(object_type, obj, autogen_context):
    """Keep migrations free of imports from the application package.

    UtcDateTime is a thin decorator over timestamptz, so a migration should say
    sa.DateTime(timezone=True) rather than reach back into app.database.
    """
    if object_type == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place, so batch mode rewrites the table
            # instead. Harmless on PostgreSQL and it keeps one migration path for both.
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
