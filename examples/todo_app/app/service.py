"""Business logic service for Todo management."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from examples.todo_app.app.models import Todo, TodoStatus
from examples.todo_app.app.repository import NotFoundError, RepositoryError, TodoRepository

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


class Priority(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class TodoService:

    def __init__(self, repo: TodoRepository) -> None:
        self.repo = repo

    async def create_todo(
        self,
        title: str,
        status: TodoStatus = TodoStatus.PENDING,
        priority: Priority = Priority.MEDIUM,
        description: Optional[str] = None,
        owner_id: Optional[int] = None,
    ) -> Todo:
        if not title:
            raise ValueError("Title must not be empty")
        if len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"Title exceeds {MAX_TITLE_LENGTH} characters")
        if description is not None and len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters")

        now = datetime.now()
        todo = Todo(
            title=title.strip(),
            description=description,
            status=status.value,
            owner_id=owner_id,
            created_at=now,
        )
        return await self.repo.create(todo)

    async def get_todo(self, todo_id: int) -> Todo:
        if todo_id <= 0:
            raise ValueError("todo_id must be positive")
        return await self.repo.get_by_id(todo_id)

    async def update_status(
        self,
        todo_id: int,
        new_status: TodoStatus,
        requester_id: Optional[int] = None,
    ) -> Todo:
        todo = await self.repo.get_by_id(todo_id)

        if todo.owner_id is not None and requester_id != todo.owner_id:
            raise PermissionError("Only the owner can update this todo")

        if todo.status == TodoStatus.DONE.value and new_status != TodoStatus.ARCHIVED:
            raise ValueError("Completed todos can only be archived")

        todo.status = new_status.value
        todo.updated_at = datetime.now()
        return await self.repo.update(todo)

    async def list_todos(
        self,
        status: Optional[TodoStatus] = None,
        owner_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[Todo]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if limit > 1000:
            raise ValueError("limit cannot exceed 1000")
        return await self.repo.list_all(status=status, owner_id=owner_id, limit=limit)

    async def delete_todo(self, todo_id: int, requester_id: Optional[int] = None) -> None:
        try:
            todo = await self.repo.get_by_id(todo_id)
        except NotFoundError:
            raise
        if todo.owner_id is not None and requester_id != todo.owner_id:
            raise PermissionError("Only the owner can delete this todo")
        await self.repo.delete(todo_id)

    def generate_share_token(self, todo_id: int, expires_in: int = 3600) -> str:
        if expires_in <= 0:
            raise ValueError("expires_in must be positive")
        token_id = uuid.uuid4()
        return f"{todo_id}:{token_id}:{expires_in}"
