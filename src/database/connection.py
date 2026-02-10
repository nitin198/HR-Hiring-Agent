"""Database connection and session management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config.settings import get_settings
from src.database.models import Base

settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,
    },
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
    finally:
        cursor.close()

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_candidates_job_description_nullable)
        await conn.run_sync(_migrate_candidate_profiles_headline)
        await conn.run_sync(_ensure_candidate_job_links)


async def drop_db() -> None:
    """Drop all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session context manager."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for FastAPI dependency injection."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _migrate_candidates_job_description_nullable(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    columns = connection.execute(text("PRAGMA table_info(candidates)")).fetchall()
    col_info = {col[1]: col for col in columns}
    job_col = col_info.get("job_description_id")
    if not job_col:
        return
    notnull = job_col[3]
    if notnull == 0:
        return

    connection.exec_driver_sql("PRAGMA foreign_keys=off;")
    connection.exec_driver_sql("BEGIN;")
    connection.exec_driver_sql(
        """
        CREATE TABLE candidates_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            phone VARCHAR(50),
            resume_text TEXT NOT NULL,
            resume_file_path VARCHAR(500),
            job_description_id INTEGER,
            created_at DATETIME,
            FOREIGN KEY(job_description_id) REFERENCES job_descriptions(id)
        );
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO candidates_new (id, name, email, phone, resume_text, resume_file_path, job_description_id, created_at)
        SELECT id, name, email, phone, resume_text, resume_file_path, job_description_id, created_at
        FROM candidates;
        """
    )
    connection.exec_driver_sql("DROP TABLE candidates;")
    connection.exec_driver_sql("ALTER TABLE candidates_new RENAME TO candidates;")
    connection.exec_driver_sql("COMMIT;")
    connection.exec_driver_sql("PRAGMA foreign_keys=on;")


def _ensure_candidate_job_links(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    connection.exec_driver_sql(
        """
        INSERT OR IGNORE INTO candidate_job_links (candidate_id, job_description_id, confidence, linked_by, created_at)
        SELECT id, job_description_id, 1.0, 'legacy', CURRENT_TIMESTAMP
        FROM candidates
        WHERE job_description_id IS NOT NULL;
        """
    )


def _migrate_candidate_profiles_headline(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    columns = connection.execute(text("PRAGMA table_info(candidate_profiles)")).fetchall()
    col_names = {col[1] for col in columns}
    if "headline" in col_names:
        return
    connection.exec_driver_sql("ALTER TABLE candidate_profiles ADD COLUMN headline VARCHAR(255);")
