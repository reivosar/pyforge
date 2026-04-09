"""Async SQLAlchemy repository for Todo CRUD operations."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from examples.todo_app.app.models import Todo, TodoStatus


class RepositoryError(Exception):
    pass


class NotFoundError(RepositoryError):
    pass


class TodoRepository:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, todo_id: int) -> Todo:
        try:
            result = await self.db.get(Todo, todo_id)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"DB error fetching todo {todo_id}") from exc
        if result is None:
            raise NotFoundError(f"Todo {todo_id} not found")
        return result

    async def list_all(
        self,
        status: Optional[TodoStatus] = None,
        owner_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[Todo]:
        try:
            stmt = select(Todo)
            if status is not None:
                stmt = stmt.where(Todo.status == status.value)
            if owner_id is not None:
                stmt = stmt.where(Todo.owner_id == owner_id)
            stmt = stmt.limit(limit)
            rows = await self.db.execute(stmt)
            return list(rows.scalars().all())
        except SQLAlchemyError as exc:
            raise RepositoryError("DB error listing todos") from exc

    async def create(self, todo: Todo) -> Todo:
        try:
            self.db.add(todo)
            await self.db.commit()
            await self.db.refresh(todo)
            return todo
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise RepositoryError("DB error creating todo") from exc

    async def update(self, todo: Todo) -> Todo:
        try:
            await self.db.commit()
            await self.db.refresh(todo)
            return todo
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise RepositoryError("DB error updating todo") from exc

    async def delete(self, todo_id: int) -> None:
        todo = await self.get_by_id(todo_id)
        try:
            await self.db.delete(todo)
            await self.db.commit()
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise RepositoryError(f"DB error deleting todo {todo_id}") from exc
