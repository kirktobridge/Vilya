"""SQLAlchemy engine factory — one engine per process."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
  """Return a process-wide SQLAlchemy engine (lazy-initialised)."""
  global _engine
  if _engine is None:
    _engine = create_engine(settings.database_url, pool_pre_ping=True)
  return _engine
