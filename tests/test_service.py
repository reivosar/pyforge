import asyncio
import sys
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from examples.todo_app.app.service import TodoService, Priority
from examples.todo_app.app.models import Todo, TodoStatus
from examples.todo_app.app.repository import NotFoundError, RepositoryError
# pip install pytest-asyncio  (needed for async tests)

class TestTodoService:

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseValueError_whenTitleIsFalse(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"Title\ must\ not\ be\ empty"):
            await sut.create_todo(title="", status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseValueError_whenTitleIsTooLong(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            await sut.create_todo(title="a" * 10001, status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseValueError_whenDescriptionIsNotNoneAndDescriptionIsTooLong(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=[0] * 10001, owner_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_returnTodo_whenCreateTodoCalledWithValidArgs(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None  # Todo

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseOrReturnNone_whenDescriptionIsNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseOrReturnNone_whenOwnerIdIsNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenPriorityIsLOW(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.LOW, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenPriorityIsMEDIUM(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenPriorityIsHIGH(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.HIGH, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenStatusIsDefaultTodostatusPendi(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenPriorityIsDefaultPriorityMedium(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenDescriptionIsDefaultNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenDescriptionIsNonDefault(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description="", owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenOwnerIdIsDefaultNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenOwnerIdIsNonDefault(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.create_todo(title='test', status=TodoStatus.PENDING, priority=Priority.MEDIUM, description=None, owner_id=1)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenTodoIdIsZeroOrNegative(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"todo_id\ must\ be\ positive"):
            await sut.get_todo(todo_id=-1)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_notRaise_whenTodoIdIsOnSafeSideAtBoundary1(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.get_todo(todo_id=1)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenTodoIdIsAtBoundary0(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            await sut.get_todo(todo_id=0)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_returnTodo_whenGetTodoCalledWithValidArgs(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.get_todo(todo_id=1)

        # Then
        assert result is not None  # Todo

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raisePermissionError_whenTodoOwnerIdIsNotNoneAndRequesterIdTodoOwnerId(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = 1
        mock_todorepository.get_by_id.return_value.status = None
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(PermissionError, match=r"Only\ the\ owner\ can\ update\ this\ todo"):
            await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseValueError_whenTodoStatusTodostatusDoneValueAndNewStatusTodostatusArchived(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        mock_todorepository.get_by_id.return_value.status = 'done'
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"Completed\ todos\ can\ only\ be\ archived"):
            await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_returnTodo_whenUpdateStatusCalledWithValidArgs(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        mock_todorepository.get_by_id.return_value.status = None
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=None)

        # Then
        assert result is not None  # Todo

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_raiseOrReturnNone_whenRequesterIdIsNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        mock_todorepository.get_by_id.return_value.status = None
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenRequesterIdIsDefaultNone(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        mock_todorepository.get_by_id.return_value.status = None
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=None)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    @patch('datetime.datetime')
    async def test_complete_whenRequesterIdIsNonDefault(self, mock_datetime_datetime, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        mock_todorepository.get_by_id.return_value.status = None
        mock_todorepository.get_by_id.return_value.updated_at = None
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.update_status(todo_id=1, new_status=MagicMock(), requester_id=1)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenLimitIsZeroOrNegative(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"limit\ must\ be\ positive"):
            await sut.list_todos(status=None, owner_id=None, limit=-1)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_notRaise_whenLimitIsOnSafeSideAtBoundary1(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=1)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenLimitIsAtBoundary0(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            await sut.list_todos(status=None, owner_id=None, limit=0)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenLimitIsGt1000(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"limit\ cannot\ exceed\ 1000"):
            await sut.list_todos(status=None, owner_id=None, limit=1001)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_notRaise_whenLimitIsOnSafeSideAtBoundary1000(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=1000)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseValueError_whenLimitIsAtBoundary1001(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            await sut.list_todos(status=None, owner_id=None, limit=1001)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_returnlist_whenListTodosCalledWithValidArgs(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None  # list

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseOrReturnNone_whenStatusIsNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseOrReturnNone_whenOwnerIdIsNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenStatusIsDefaultNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenStatusIsNonDefault(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=MagicMock(), owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenOwnerIdIsDefaultNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenOwnerIdIsNonDefault(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=1, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenLimitIsDefault50(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=50)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenLimitIsNonDefault(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = await sut.list_todos(status=None, owner_id=None, limit=25)

        # Then
        assert result is not None

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseNotFoundError_whenDependencyRaisesNotFoundError(self, mock_todorepository):
        mock_todorepository.delete = AsyncMock(side_effect=NotFoundError('mocked error'))
        mock_todorepository.get_by_id.return_value.owner_id = None
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(NotFoundError):
            await sut.delete_todo(todo_id=1, requester_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raisePermissionError_whenTodoOwnerIdIsNotNoneAndRequesterIdTodoOwnerId(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = 1
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(PermissionError, match=r"Only\ the\ owner\ can\ delete\ this\ todo"):
            await sut.delete_todo(todo_id=1, requester_id=None)

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_callDependency_whenDeleteTodoInvokedWithValidArgs(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        sut = TodoService(repo=mock_todorepository)

        # When
        await sut.delete_todo(todo_id=1, requester_id=None)

        # Then
        mock_todorepository.delete.assert_called_once()
        mock_todorepository.get_by_id.assert_called_once()

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_raiseOrReturnNone_whenRequesterIdIsNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        sut = TodoService(repo=mock_todorepository)

        # When
        await sut.delete_todo(todo_id=1, requester_id=None)

        # Then
        mock_todorepository.delete.assert_called_once()
        mock_todorepository.get_by_id.assert_called_once()

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenRequesterIdIsDefaultNone(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        sut = TodoService(repo=mock_todorepository)

        # When
        await sut.delete_todo(todo_id=1, requester_id=None)

        # Then
        mock_todorepository.delete.assert_called_once()
        mock_todorepository.get_by_id.assert_called_once()

    @pytest.mark.asyncio
    @patch('examples.todo_app.app.service.TodoRepository', new_callable=AsyncMock)
    async def test_complete_whenRequesterIdIsNonDefault(self, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        mock_todorepository.get_by_id.return_value.owner_id = None
        sut = TodoService(repo=mock_todorepository)

        # When
        await sut.delete_todo(todo_id=1, requester_id=1)

        # Then
        mock_todorepository.delete.assert_called_once()
        mock_todorepository.get_by_id.assert_called_once()

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_raiseValueError_whenExpiresInIsZeroOrNegative(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError, match=r"expires_in\ must\ be\ positive"):
            sut.generate_share_token(todo_id=1, expires_in=-1)

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_notRaise_whenExpiresInIsOnSafeSideAtBoundary1(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = sut.generate_share_token(todo_id=1, expires_in=1)

        # Then
        assert isinstance(result, str)

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_raiseValueError_whenExpiresInIsAtBoundary0(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        # Then
        with pytest.raises(ValueError):
            sut.generate_share_token(todo_id=1, expires_in=0)

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_returnstr_whenGenerateShareTokenCalledWithValidArgs(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = sut.generate_share_token(todo_id=1, expires_in=3600)

        # Then
        assert result is not None  # str

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_complete_whenExpiresInIsDefault3600(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = sut.generate_share_token(todo_id=1, expires_in=3600)

        # Then
        assert isinstance(result, str)

    @patch('examples.todo_app.app.service.TodoRepository')
    @patch('uuid.uuid4')
    def test_complete_whenExpiresInIsNonDefault(self, mock_uuid_uuid4, mock_todorepository):
        mock_todorepository.return_value = MagicMock()
        sut = TodoService(repo=mock_todorepository)

        # When
        result = sut.generate_share_token(todo_id=1, expires_in=1800)

        # Then
        assert isinstance(result, str)

