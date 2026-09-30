from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware on the way in and on the way out.

    PostgreSQL returns an aware value for timestamptz. SQLite returns a naive one, so a
    comparison against an aware "now" raises there and works in production. Normalising in
    one type means no caller has to remember which database it is talking to.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


settings = get_settings()
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

if settings.database_url.startswith("sqlite"):
    # pysqlite commits DDL implicitly and does not emit BEGIN where SQLAlchemy expects it,
    # so a rollback can leave work behind. Taking control of the transaction is the fix
    # SQLAlchemy documents for this driver. PostgreSQL needs none of it.

    @event.listens_for(engine, "connect")
    def _disable_driver_transaction_handling(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection):
        connection.exec_driver_sql("BEGIN")
