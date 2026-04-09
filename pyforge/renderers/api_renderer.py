"""API test renderer for Python (FastAPI/Flask/Django)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from pyforge.cases.branch import _camel


def detect_api_framework(source: str) -> str | None:
    """Return API framework name if file contains route definitions."""
    if re.search(r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(", source):
        return "fastapi"
    if re.search(r"@(?:app|bp)\.route\s*\(", source):
        return "flask"
    if re.search(r"urlpatterns\s*=", source):
        return "django"
    return None


def _extract_fastapi_endpoints(source: str) -> list[dict]:
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
            endpoints.append({
                "method": http_method, "path": path, "handler": node.name,
                "path_params": path_params,
                "has_body": http_method in ("POST", "PUT", "PATCH"),
                "has_auth": has_auth, "response_model": response_model,
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
) -> str:
    if not endpoints:
        return ""

    if api_framework == "fastapi":
        client_setup = (
            f"from fastapi.testclient import TestClient\n"
            f"from {module_path} import app\n"
            f"client = TestClient(app)"
        )
    else:
        client_setup = f"from {module_path} import app\nclient = app.test_client()"

    lines = [
        "import pytest",
        "from unittest.mock import patch, MagicMock",
        "",
        client_setup,
        "",
        "",
    ]

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
        status_ok = 200 if ep["method"] != "POST" else 201

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
            lines.append(f"        response = client.{method_lower}('{sample_path}', json={{}})")
        else:
            lines.append(f"        response = client.{method_lower}('{sample_path}')")
        lines += [f"", f"        # Then", f"        assert response.status_code == {status_ok}"]

        if ep["path_params"]:
            nonexistent = re.sub(r"\{(\w+)\}", "999999", ep["path"])
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
                f"        response = client.post('{sample_path}', json=None)",
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
) -> str:
    """Extract endpoints and render an API test file."""
    if api_framework == "fastapi":
        endpoints = _extract_fastapi_endpoints(source)
    elif api_framework == "flask":
        endpoints = _extract_flask_endpoints(source)
    else:
        # Django: delegate to Claude (URL patterns require project context)
        return ""

    return generate_api_test_python(module_path, api_framework, endpoints)
