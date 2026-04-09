"""SQLAlchemy ORM models for the Todo application."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TodoStatus(str, Enum):
    PENDING  = "pending"
    ACTIVE   = "active"
    DONE     = "done"
    ARCHIVED = "archived"


class Todo(Base):
    __tablename__ = "todos"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status      = Column(String(20), default=TodoStatus.PENDING.value)
    priority    = Column(Integer, default=0)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True)
    email    = Column(String(255), nullable=False, unique=True)
    todos    = relationship("Todo", backref="owner", foreign_keys=[Todo.owner_id])
