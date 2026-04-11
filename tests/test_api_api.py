import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient
from examples.todo_app.app.api import app
from examples.todo_app.app.api import get_service

@pytest.fixture(autouse=True)
def _override_dependencies():
    """Override FastAPI dependencies with mocks."""
    mock_service = MagicMock()
    # Create a mock Todo object that passes Pydantic validation
    mock_todo = MagicMock()
    mock_todo.id = 1
    mock_todo.title = 'Test Todo'
    mock_todo.status = 'pending'
    mock_todo.description = 'Test description'
    mock_todo.owner_id = None
    mock_service.list_todos = AsyncMock(return_value=[])
    mock_service.get_todo = AsyncMock(return_value=mock_todo)
    mock_service.create_todo = AsyncMock(return_value=mock_todo)
    mock_service.update_status = AsyncMock(return_value=mock_todo)
    mock_service.delete_todo = AsyncMock(return_value=None)
    app.dependency_overrides[get_service] = lambda: mock_service
    yield
    app.dependency_overrides.clear()

client = TestClient(app)


class TestListTodosTodos:

    def test_returnOk_whenListTodosTodosCalledWithValidInput(self):
        # When
        response = client.get('/todos/')

        # Then
        assert response.status_code == 200

class TestCreateTodoTodos:

    def test_returnTodoResponse_whenCreateTodoTodosCalledWithValidInput(self):
        # When
        response = client.post('/todos/', json={'title': 'test'})

        # Then
        assert response.status_code == 201

    def test_return422_whenCreateTodoTodosCalledWithInvalidBody(self):
        response = client.post('/todos/', json=None)
        assert response.status_code == 422

class TestGetTodoTodosTodoId:

    def test_returnTodoResponse_whenGetTodoTodosTodoIdCalledWithValidInput(self):
        # When
        response = client.get('/todos/1')

        # Then
        assert response.status_code == 200

    def test_return404_whenGetTodoTodosTodoIdCalledWithNonexistentId(self):
        from fastapi import HTTPException
        from examples.todo_app.app.api import get_service
        notfound = MagicMock()
        notfound.get_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.update_status = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.delete_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        app.dependency_overrides[get_service] = lambda: notfound
        response = client.get('/todos/999999')
        app.dependency_overrides.clear()
        assert response.status_code == 404

class TestUpdateTodoTodosTodoId:

    def test_returnTodoResponse_whenUpdateTodoTodosTodoIdCalledWithValidInput(self):
        # When
        response = client.put('/todos/1', json={'new_status': 'pending'})

        # Then
        assert response.status_code == 200

    def test_return404_whenUpdateTodoTodosTodoIdCalledWithNonexistentId(self):
        from fastapi import HTTPException
        from examples.todo_app.app.api import get_service
        notfound = MagicMock()
        notfound.get_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.update_status = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.delete_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        app.dependency_overrides[get_service] = lambda: notfound
        response = client.put('/todos/999999', json={'new_status': 'pending'})
        app.dependency_overrides.clear()
        assert response.status_code == 404

    def test_return422_whenUpdateTodoTodosTodoIdCalledWithInvalidBody(self):
        response = client.put('/todos/1', json=None)
        assert response.status_code == 422

class TestDeleteTodoTodosTodoId:

    def test_returnOk_whenDeleteTodoTodosTodoIdCalledWithValidInput(self):
        # When
        response = client.delete('/todos/1')

        # Then
        assert response.status_code == 204

    def test_return404_whenDeleteTodoTodosTodoIdCalledWithNonexistentId(self):
        from fastapi import HTTPException
        from examples.todo_app.app.api import get_service
        notfound = MagicMock()
        notfound.get_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.update_status = AsyncMock(side_effect=HTTPException(status_code=404))
        notfound.delete_todo = AsyncMock(side_effect=HTTPException(status_code=404))
        app.dependency_overrides[get_service] = lambda: notfound
        response = client.delete('/todos/999999')
        app.dependency_overrides.clear()
        assert response.status_code == 404
