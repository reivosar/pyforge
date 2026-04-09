import pytest
from unittest.mock import AsyncMock, MagicMock
from examples.todo_app.app.models import Todo, TodoStatus
from examples.todo_app.app.repository import TodoRepository, NotFoundError


@pytest.fixture
def mock_todo_repository():
    """Create a properly configured mock repository."""
    repo = AsyncMock(spec=TodoRepository)
    
    # Setup default return values for async methods
    async def mock_create(todo):
        return todo
    
    async def mock_get_by_id(todo_id):
        if todo_id <= 0:
            raise ValueError("Invalid todo_id")
        todo = MagicMock(spec=Todo)
        todo.id = todo_id
        todo.owner_id = None
        todo.status = TodoStatus.PENDING.value
        return todo
    
    async def mock_list_all(status=None, owner_id=None, limit=50):
        return []
    
    async def mock_update(todo):
        return todo
    
    async def mock_delete(todo_id):
        pass
    
    repo.create = AsyncMock(side_effect=mock_create)
    repo.get_by_id = AsyncMock(side_effect=mock_get_by_id)
    repo.list_all = AsyncMock(side_effect=mock_list_all)
    repo.update = AsyncMock(side_effect=mock_update)
    repo.delete = AsyncMock(side_effect=mock_delete)
    
    return repo
