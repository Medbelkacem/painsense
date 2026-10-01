from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from config import get_settings


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
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
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _disable_driver_transaction_handling(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        # Write-ahead logging lets the form's dozen reads go through while an audit entry
        # is being signed and written; in the default journal mode they queue behind it
        # and time out as "database is locked".
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _emit_begin(connection):
        # A request's transaction is IMMEDIATE rather than DEFERRED. Nearly every request
        # reads first and writes afterwards (even reading a patient records an audit
        # entry), and a deferred transaction cannot upgrade its lock once another writer
        # has committed: SQLite fails it on the spot instead of waiting. Taking the write
        # lock up front means requests queue, for up to the busy timeout, and none fails.
        # Everything else (start-up seeding, the CLI, the test harness) stays deferred.
        immediate = connection.get_execution_options().get("sqlite_immediate", False)
        connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")


def request_connection():
    """A connection for one HTTP request, with the SQLite locking rule above applied."""
    return engine.connect().execution_options(sqlite_immediate=True)


def serialise_appends(session, name: str) -> None:
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": hash(name) & 0x7FFFFFFF}
        )
