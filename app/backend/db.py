"""
Database layer (SQLAlchemy).

Runs on SQLite for local dev and Postgres in production — controlled entirely by the
DATABASE_URL env var. This is what lets votes and user libraries persist across container
instances (point every instance at the same hosted Postgres).

  local dev :  DATABASE_URL unset  ->  sqlite:///./promptfinder.db
  prod      :  DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/promptfinder
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (create_engine, String, Integer, DateTime, ForeignKey,
                        UniqueConstraint, func)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./promptfinder.db")

# SQLite needs check_same_thread=False for the threaded dev server; Postgres ignores it.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    saved = relationship("SavedPrompt", back_populates="user", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"
    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(8))   # 'worked' | 'didnt'
    model: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SavedPrompt(Base):
    __tablename__ = "saved_prompts"
    __table_args__ = (UniqueConstraint("user_id", "prompt_id", name="uq_user_prompt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    user = relationship("User", back_populates="saved")


def init_db():
    Base.metadata.create_all(engine)


# expose func for aggregate queries
count = func.count
