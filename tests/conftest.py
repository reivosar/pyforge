"""Shared pytest fixtures for pyforge tests."""
import ast
from pathlib import Path
from typing import Any

import pytest

from pyforge.analysis.python_ast import _parse_method_node
from pyforge.models import MethodInfo


@pytest.fixture
def make_method():
    """Factory to create MethodInfo with sensible defaults.

    Usage:
        method = make_method(name="foo", args=["x"], arg_types={"x": "int"})
    """
    def factory(
        name: str = "test_method",
        args: list[str] | None = None,
        arg_types: dict[str, str] | None = None,
        return_type: str | None = "int",
        is_void: bool = False,
        is_public: bool = True,
        is_async: bool = False,
        is_static: bool = False,
        is_classmethod: bool = False,
        raises: list[str] | None = None,
        arg_defaults: dict[str, str] | None = None,
        nondeterministic_patches: list[str] | None = None,
        ast_node: Any = None,
    ) -> MethodInfo:
        return MethodInfo(
            name=name,
            args=args or [],
            arg_types=arg_types or {},
            return_type=return_type,
            is_void=is_void,
            is_public=is_public,
            is_async=is_async,
            is_static=is_static,
            is_classmethod=is_classmethod,
            raises=raises or [],
            arg_defaults=arg_defaults or {},
            nondeterministic_patches=nondeterministic_patches or [],
            ast_node=ast_node,
        )

    return factory


@pytest.fixture
def parse_fn_ast():
    """Parse Python source string and return the first function/class definition.

    Usage:
        fn_node = parse_fn_ast("def foo(x: int) -> int: return x + 1")
    """
    def _parse(source: str) -> ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef:
        tree = ast.parse(source)
        if not tree.body:
            raise ValueError("No definitions found in source")
        return tree.body[0]

    return _parse


@pytest.fixture
def method_with_ast(parse_fn_ast, tmp_path):
    """Build MethodInfo from Python source string via _parse_method_node.

    Usage:
        method = method_with_ast("def foo(x: int) -> str: return str(x)")
    """
    def _build(
        source: str,
        class_context: bool = False,
        arg_defaults: dict[str, str] | None = None,
    ) -> MethodInfo:
        # If class context, wrap in a class definition
        if class_context:
            source = f"class TestClass:\n" + "\n".join(f"    {line}" for line in source.split("\n"))
            tree = ast.parse(source)
            fn_node = tree.body[0].body[0]  # Get method from class
        else:
            fn_node = parse_fn_ast(source)

        # Create a temp module for _parse_method_node
        temp_file = tmp_path / "temp.py"
        temp_file.write_text(source)

        # Call _parse_method_node
        method_info = _parse_method_node(
            fn_node,
            root=tmp_path.parent,
            arg_defaults=arg_defaults or {},
        )
        return method_info

    return _build


@pytest.fixture
def tmp_py_file(tmp_path):
    """Create a temporary Python file with given source.

    Usage:
        path = tmp_py_file("def foo(): pass")
    """
    def _write(source: str, filename: str = "source.py") -> Path:
        file_path = tmp_path / filename
        file_path.write_text(source)
        return file_path

    return _write


@pytest.fixture
def service_py_path() -> Path:
    """Path to the example TodoService."""
    return Path("/Users/mac/workspace/pyforge/examples/todo_app/app/service.py")


@pytest.fixture
def models_py_path() -> Path:
    """Path to the example Todo ORM models."""
    return Path("/Users/mac/workspace/pyforge/examples/todo_app/app/models.py")


@pytest.fixture
def repository_py_path() -> Path:
    """Path to the example TodoRepository."""
    return Path("/Users/mac/workspace/pyforge/examples/todo_app/app/repository.py")
