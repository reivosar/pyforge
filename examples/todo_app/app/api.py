"""FastAPI application for the Todo API."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from examples.todo_app.app.models import TodoStatus
from examples.todo_app.app.service import TodoService

app = FastAPI(title="Todo API")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TodoCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: TodoStatus = TodoStatus.PENDING
    owner_id: Optional[int] = None


class TodoUpdate(BaseModel):
    new_status: TodoStatus
    requester_id: Optional[int] = None


class TodoResponse(BaseModel):
    id: int
    title: str
    status: str
    description: Optional[str] = None
    owner_id: Optional[int] = None


# ── Dependency ────────────────────────────────────────────────────────────────

def get_service() -> TodoService:
    raise NotImplementedError("Override with DI")


# ── Endpoints (sync def — required for pyforge AST detection) ─────────────────

@app.get("/todos/", response_model=list[TodoResponse])
def list_todos(
    status: Optional[TodoStatus] = None,
    owner_id: Optional[int] = None,
    service: TodoService = Depends(get_service),
):
    try:
        return asyncio.run(service.list_todos(status=status, owner_id=owner_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/todos/", response_model=TodoResponse, status_code=201)
def create_todo(
    payload: TodoCreate,
    service: TodoService = Depends(get_service),
):
    try:
        return asyncio.run(service.create_todo(
            title=payload.title,
            description=payload.description,
            status=payload.status,
            owner_id=payload.owner_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/todos/{todo_id}", response_model=TodoResponse)
def get_todo(todo_id: int, service: TodoService = Depends(get_service)):
    try:
        return asyncio.run(service.get_todo(todo_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/todos/{todo_id}", response_model=TodoResponse)
def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    service: TodoService = Depends(get_service),
):
    try:
        return asyncio.run(service.update_status(
            todo_id=todo_id,
            new_status=payload.new_status,
            requester_id=payload.requester_id,
        ))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(
    todo_id: int,
    service: TodoService = Depends(get_service),
):
    try:
        asyncio.run(service.delete_todo(todo_id))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
