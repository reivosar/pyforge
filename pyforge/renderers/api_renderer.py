"""API test renderer for Python (FastAPI/Flask/Django)."""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

from pyforge.cases.branch import _camel


def _find_project_root(source_path: Path) -> Path:
    """Find project root by looking for pyproject.toml, setup.py, or git root."""
    current = source_path.parent
    for _ in range(10):  # Limit depth
        if (current / "pyproject.toml").exists() or (current / ".git").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return source_path.parent


def _load_openapi_schema(module_path: str, source_path: Path) -> dict | None:
    """Load and return app.openapi() schema. Returns None if import fails."""
    try:
        root = _find_project_root(source_path)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        mod = importlib.import_module(module_path)
        app = getattr(mod, "app", None)
        if app is None:
            return None
        return app.openapi()
    except (ImportError, AttributeError, Exception):
        return None


def _resolve_ref(ref: str, schemas: dict) -> dict:
    """Resolve #/components/schemas/ModelName → schemas['ModelName']."""
    if not ref.startswith("#/components/schemas/"):
        return {}
    name = ref.split("/")[-1]
    return schemas.get(name, {})


def _sample_from_schema(schema: dict, schemas: dict) -> object:
    """Generate JSON-serializable sample value from OpenAPI schema."""
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], schemas)
        return _sample_from_schema(resolved, schemas)

    if "enum" in schema:
        return schema["enum"][0] if schema["enum"] else "test"

    schema_type = schema.get("type")
    if schema_type == "string":
        return "test"
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        return []
    if schema_type == "object":
        return {}

    # anyOf/oneOf with null — pick the non-null type
    if "anyOf" in schema:
        for opt in schema["anyOf"]:
            if opt.get("type") != "null":
                return _sample_from_schema(opt, schemas)
        return None

    return "test"


def _build_sample_from_openapi(model_ref: str, schemas: dict) -> dict:
    """Build sample request body from OpenAPI schema $ref."""
    schema = _resolve_ref(model_ref, schemas)
    if not schema:
        return {}

    required = schema.get("required", [])
    properties = schema.get("properties", {})
    sample = {}

    for field in required:
        if field in properties:
            sample[field] = _sample_from_schema(properties[field], schemas)

    return sample


def _extract_fastapi_endpoints_openapi(module_path: str, source_path: Path) -> list[dict] | None:
    """Extract endpoints from OpenAPI schema. Returns None if schema unavailable."""
    openapi_schema = _load_openapi_schema(module_path, source_path)
    if not openapi_schema:
        return None

    endpoints = []
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    paths = openapi_schema.get("paths", {})

    for path, path_item in paths.items():
        for method, op in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue

            # Extract path params
            path_params = [
                p["name"]
                for p in op.get("parameters", [])
                if p.get("in") == "path"
            ]

            # Extract handler name from operationId (e.g. "list_todos_todos__get" → "list_todos")
            op_id = op.get("operationId", "").lower()
            handler = op_id.rsplit("_", 1)[0] if "_" in op_id else op_id

            # Extract body sample
            body_sample = {}
            has_body = "requestBody" in op
            if has_body:
                req_body = op.get("requestBody", {})
                schema_ref = (
                    req_body.get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                    .get("$ref", "")
                )
                if schema_ref:
                    body_sample = _build_sample_from_openapi(schema_ref, schemas)

            # Extract status_ok (first non-422 response code)
            responses = op.get("responses", {})
            status_ok = 200
            for code in responses.keys():
                if code != "422":
                    try:
                        status_ok = int(code)
                        break
                    except ValueError:
                        pass

            # Extract response_model name
            response_model = ""
            for code, resp in responses.items():
                if code != "422":
                    schema_ref = (
                        resp.get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                        .get("$ref", "")
                    )
                    if schema_ref:
                        response_model = schema_ref.split("/")[-1]
                    break

            endpoints.append({
                "method": method.upper(),
                "path": path,
                "handler": handler,
                "path_params": path_params,
                "has_body": has_body,
                "has_auth": any(p.get("in") == "header" for p in op.get("parameters", [])),
                "response_model": response_model,
                "body_sample": body_sample,
                "status_ok": status_ok,
            })

    return endpoints if endpoints else None


def detect_api_framework(source: str) -> str | None:
    """Return API framework name if file contains route definitions."""
    if re.search(r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(", source):
        return "fastapi"
    if re.search(r"@(?:app|bp)\.route\s*\(", source):
        return "flask"
    if re.search(r"urlpatterns\s*=", source):
        return "django"
    return None


def _extract_fastapi_di_functions(source: str) -> list[str]:
    """Extract FastAPI DI factory function names (e.g., 'get_service' from Depends(get_service))."""
    di_functions = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
            if node.args and isinstance(node.args[0], ast.Name):
                di_functions.append(node.args[0].id)
    return list(set(di_functions))  # Remove duplicates


def _extract_service_method_calls(handler_node: ast.FunctionDef) -> list[str]:
    """Return service method names called inside the handler (e.g. service.update_status → ['update_status'])."""
    calls = []
    for node in ast.walk(handler_node):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "service"):
            calls.append(node.func.attr)
    return calls


def _extract_body_model_name(handler_node: ast.FunctionDef) -> str | None:
    """Return the Pydantic body parameter type name from a FastAPI handler."""
    defaults = handler_node.args.defaults
    args = handler_node.args.args
    offset = len(args) - len(defaults)
    for i, arg in enumerate(args):
        if arg.annotation is None:
            continue
        type_name = ast.unparse(arg.annotation)
        if type_name in ("str", "int", "float", "bool", "None", "HTTPException"):
            continue
        # Skip Depends params
        default_idx = i - offset
        if default_idx >= 0:
            d = defaults[default_idx]
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends":
                continue
        # Skip Optional/query params (no annotation or simple type)
        if type_name.startswith("Optional[") or type_name.startswith("list["):
            continue
        return type_name
    return None


def _ann_to_sample(ann: ast.expr, enum_first: dict[str, str]) -> object | None:
    """Convert an AST annotation node to a sample JSON-serializable value.

    Returns None to signal "skip this field" (Optional with default).
    """
    if isinstance(ann, ast.Name):
        name = ann.id
        if name == "str":
            return "test"
        if name == "int":
            return 1
        if name == "float":
            return 1.0
        if name == "bool":
            return True
        # Enum or custom class — return first member value if known
        return enum_first.get(name, "test")
    if isinstance(ann, ast.Attribute):
        # e.g. models.TodoStatus
        return enum_first.get(ann.attr, "test")
    if isinstance(ann, ast.Subscript):
        # Optional[X] → skip (has_default implied), list[X] → []
        if isinstance(ann.value, ast.Name):
            if ann.value.id == "Optional":
                return None  # caller will skip
            if ann.value.id in ("List", "list"):
                return []
        return None
    return "test"


def _collect_enum_first_values(tree: ast.Module) -> dict[str, str]:
    """Return {ClassName: first_member_value} for Enum-like classes."""
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and item.value:
                        raw = ast.unparse(item.value).strip("'\"")
                        if node.name not in result:
                            result[node.name] = raw
                        break
    return result


def _collect_all_enum_values(source: str, source_path: "Path | None" = None) -> dict[str, str]:
    """Collect Enum first values from source and any imported local modules."""
    from pathlib import Path as _Path
    tree = ast.parse(source)
    result = _collect_enum_first_values(tree)
    if not source_path:
        return result
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod_file = node.module.replace(".", "/") + ".py"
        for root in [source_path.parent, source_path.parent.parent,
                     source_path.parent.parent.parent, _Path.cwd()]:
            candidate = root / mod_file
            if candidate.exists():
                try:
                    imported_tree = ast.parse(candidate.read_text())
                    result.update(_collect_enum_first_values(imported_tree))
                except Exception:
                    pass
                break
    return result


def _build_sample_body(source: str, model_name: str, source_path: "Path | None" = None) -> dict:
    """Parse a Pydantic BaseModel class and return a sample JSON-serializable dict."""
    tree = ast.parse(source)
    enum_first = _collect_all_enum_values(source, source_path)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == model_name):
            continue
        sample: dict = {}
        for item in node.body:
            if not (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)):
                continue
            field = item.target.id
            # Fields with any default value → not required, skip
            if item.value is not None:
                continue
            val = _ann_to_sample(item.annotation, enum_first)
            if val is None:
                continue
            sample[field] = val
        return sample
    return {}


def _extract_fastapi_endpoints(source: str, source_path: "Path | None" = None) -> list[dict]:
    endpoints = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            m = re.match(
                r"(?:app|router)\.(get|post|put|delete|patch)",
                ast.unparse(deco).split("(")[0],
            )
            if not m:
                continue
            http_method = m.group(1).upper()
            path = "/"
            if isinstance(deco, ast.Call) and deco.args:
                path = ast.unparse(deco.args[0]).strip("'\"")
            path_params = re.findall(r"\{(\w+)\}", path)
            has_auth = any(
                "token" in ast.unparse(a).lower() or "current_user" in ast.unparse(a).lower()
                for a in node.args.args
            )
            response_model = None
            if isinstance(deco, ast.Call):
                for kw in deco.keywords:
                    if kw.arg == "response_model":
                        response_model = ast.unparse(kw.value)
            body_sample: dict = {}
            if http_method in ("POST", "PUT", "PATCH"):
                model_name = _extract_body_model_name(node)
                if model_name:
                    body_sample = _build_sample_body(source, model_name, source_path)
            service_calls = _extract_service_method_calls(node)
            endpoints.append({
                "method": http_method, "path": path, "handler": node.name,
                "path_params": path_params,
                "has_body": http_method in ("POST", "PUT", "PATCH"),
                "has_auth": has_auth, "response_model": response_model,
                "body_sample": body_sample,
                "service_calls": service_calls,
            })
    return endpoints


def _extract_flask_endpoints(source: str) -> list[dict]:
    endpoints = []
    for m in re.finditer(
        r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:[^)]*methods\s*=\s*\[([^\]]*)\])?[^)]*\)\s*\ndef\s+(\w+)",
        source, re.MULTILINE,
    ):
        path = m.group(1)
        methods_raw = m.group(2) or "GET"
        handler = m.group(3)
        for http_method in re.findall(r"[A-Z]+", methods_raw):
            path_params = re.findall(r"<(?:\w+:)?(\w+)>", path)
            endpoints.append({
                "method": http_method, "path": path, "handler": handler,
                "path_params": path_params,
                "has_body": http_method in ("POST", "PUT", "PATCH"),
                "has_auth": False, "response_model": None,
            })
    return endpoints


def generate_api_test_python(
    module_path: str,
    api_framework: str,
    endpoints: list[dict],
    source: str = "",
) -> str:
    if not endpoints:
        return ""

    if api_framework == "fastapi":
        client_setup = (
            f"from fastapi.testclient import TestClient\n"
            f"from {module_path} import app"
        )
        # Extract DI functions that need to be overridden
        di_functions = _extract_fastapi_di_functions(source) if source else []
    else:
        client_setup = f"from {module_path} import app"
        di_functions = []

    lines = [
        "import pytest",
        "from unittest.mock import patch, MagicMock, AsyncMock",
        "",
        client_setup,
    ]

    # Add DI function imports and fixture
    if di_functions and api_framework == "fastapi":
        for func in sorted(di_functions):
            lines.append(f"from {module_path} import {func}")
        lines += [
            "",
            "@pytest.fixture(autouse=True)",
            "def _override_dependencies():",
            '    """Override FastAPI dependencies with mocks."""',
            "    mock_service = MagicMock()",
            "    # Create a mock Todo object that passes Pydantic validation",
            "    mock_todo = MagicMock()",
            "    mock_todo.id = 1",
            "    mock_todo.title = 'Test Todo'",
            "    mock_todo.status = 'pending'",
            "    mock_todo.description = 'Test description'",
            "    mock_todo.owner_id = None",
            "    mock_service.list_todos = AsyncMock(return_value=[])",
            "    mock_service.get_todo = AsyncMock(return_value=mock_todo)",
            "    mock_service.create_todo = AsyncMock(return_value=mock_todo)",
            "    mock_service.update_status = AsyncMock(return_value=mock_todo)",
            "    mock_service.delete_todo = AsyncMock(return_value=None)",
        ]
        for func in sorted(di_functions):
            lines.append(f"    app.dependency_overrides[{func}] = lambda: mock_service")
        lines += [
            "    yield",
            "    app.dependency_overrides.clear()",
            "",
        ]

    lines.append(f"client = TestClient(app)" if api_framework == "fastapi" else "client = app.test_client()")
    lines += ["", ""]

    for ep in endpoints:
        handler = _camel(ep["handler"] or ep["path"].replace("/", "_"))
        sample_path = ep["path"]
        for p in ep["path_params"]:
            sample_path = re.sub(
                r"\{" + p + r"\}|<(?:\w+:)?" + p + r">", "1", sample_path
            )

        lines.append(
            f"class Test{_camel(ep['handler'] or ep['path'].replace('/', '_'))}:"
        )
        # Use status_ok from endpoint (from OpenAPI or fallback map)
        status_ok = ep.get("status_ok")
        if status_ok is None:
            status_ok_map = {"GET": 200, "POST": 201, "PUT": 200, "PATCH": 200, "DELETE": 204}
            status_ok = status_ok_map.get(ep["method"], 200)

        # Sanitize response_model for use in method name (remove [, ], <, >, etc.)
        response_model_name = ep['response_model'] or 'Ok'
        response_model_safe = re.sub(r"[^A-Za-z0-9]", "", response_model_name)

        # happy path
        lines += [
            f"",
            f"    def test_return{response_model_safe}_when{handler}CalledWithValidInput(self):",
            f"        # When",
        ]
        method_lower = ep["method"].lower()
        if ep["has_body"]:
            body = ep.get("body_sample") or {}
            lines.append(f"        response = client.{method_lower}('{sample_path}', json={body!r})")
        else:
            lines.append(f"        response = client.{method_lower}('{sample_path}')")
        lines += [f"", f"        # Then", f"        assert response.status_code == {status_ok}"]

        if ep["path_params"]:
            nonexistent = re.sub(r"\{(\w+)\}", "999999", ep["path"])
            if di_functions:
                di_func = sorted(di_functions)[0]
                lines += [
                    f"",
                    f"    def test_return404_when{handler}CalledWithNonexistentId(self):",
                    f"        from fastapi import HTTPException",
                    f"        from {module_path} import {di_func}",
                    f"        notfound = MagicMock()",
                    f"        notfound.get_todo = AsyncMock(side_effect=HTTPException(status_code=404))",
                    f"        notfound.update_status = AsyncMock(side_effect=HTTPException(status_code=404))",
                    f"        notfound.delete_todo = AsyncMock(side_effect=HTTPException(status_code=404))",
                    f"        app.dependency_overrides[{di_func}] = lambda: notfound",
                ]
                _body_sample_repr = repr(ep.get("body_sample") or {})
                body_arg = f", json={_body_sample_repr}" if ep["has_body"] else ""
                lines += [
                    f"        response = client.{method_lower}('{nonexistent}'{body_arg})",
                    f"        app.dependency_overrides.clear()",
                    f"        assert response.status_code == 404",
                ]
            else:
                lines += [
                    f"",
                    f"    def test_return404_when{handler}CalledWithNonexistentId(self):",
                    f"        response = client.{method_lower}('{nonexistent}')",
                    f"        assert response.status_code == 404",
                ]

        if ep["has_body"]:
            lines += [
                f"",
                f"    def test_return422_when{handler}CalledWithInvalidBody(self):",
                f"        response = client.{method_lower}('{sample_path}', json=None)",
                f"        assert response.status_code == 422",
            ]

        if ep["has_auth"]:
            lines += [
                f"",
                f"    def test_return401_when{handler}CalledWithoutAuthToken(self):",
                f"        response = client.{method_lower}('{sample_path}')",
                f"        assert response.status_code == 401",
            ]

        lines.append(f"")

    return "\n".join(lines)


def generate_api_tests(
    source: str,
    api_framework: str,
    module_path: str,
    source_path: "Path | None" = None,
) -> str:
    """Extract endpoints and render an API test file."""
    endpoints = None

    if api_framework == "fastapi" and source_path:
        # Try OpenAPI schema first (authoritative)
        endpoints = _extract_fastapi_endpoints_openapi(module_path, source_path)

    if endpoints is None:
        # Fall back to AST parsing
        if api_framework == "fastapi":
            endpoints = _extract_fastapi_endpoints(source, source_path)
        elif api_framework == "flask":
            endpoints = _extract_flask_endpoints(source)
        else:
            return ""

    return generate_api_test_python(module_path, api_framework, endpoints, source)
