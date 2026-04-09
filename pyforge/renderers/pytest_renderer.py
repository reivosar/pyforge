"""pytest test file renderer for Python sources."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from pyforge.analysis.python_ast import _type_sample, detect_enum_types
from pyforge.cases import TIER_GENERATORS, generate_cases
from pyforge.cases.branch import _camel, analyze_method_branches
from pyforge.cases.extreme import build_hypothesis_test
from pyforge.models import BranchCase, ClassInfo, DepInfo, MethodInfo, SourceInfo
from pyforge.runtime.capture import try_execute_and_capture


# ── DB mock specs ─────────────────────────────────────────────────────────────

_PYTHON_DB_MOCKS: dict[str, tuple[str, list[str]]] = {
    "sqlalchemy": (
        "sqlalchemy_session",
        [
            "mock_{attr} = AsyncMock()",
            "mock_{attr}.get = AsyncMock(return_value=MagicMock())",
            "mock_{attr}.execute = AsyncMock(return_value=MagicMock())",
            "mock_{attr}.add = MagicMock(return_value=None)",
            "mock_{attr}.commit = AsyncMock(return_value=None)",
            "mock_{attr}.rollback = AsyncMock(return_value=None)",
            "mock_{attr}.refresh = AsyncMock(return_value=None)",
            "mock_{attr}.delete = AsyncMock(return_value=None)",
        ],
    ),
    "django.db": (
        "django_orm",
        [
            "# Django ORM: use @pytest.mark.django_db on the test class",
            "# or mock the queryset:",
            "mock_{attr} = MagicMock()",
            "mock_{attr}.filter.return_value = mock_{attr}",
            "mock_{attr}.exclude.return_value = mock_{attr}",
            "mock_{attr}.first.return_value = None",
            "mock_{attr}.all.return_value = []",
        ],
    ),
    "psycopg2": (
        "psycopg2",
        [
            "mock_{attr} = MagicMock()",
            "mock_cursor = MagicMock()",
            "mock_{attr}.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)",
            "mock_{attr}.cursor.return_value.__exit__ = MagicMock(return_value=False)",
            "mock_cursor.fetchone.return_value = None",
            "mock_cursor.fetchall.return_value = []",
            "mock_cursor.rowcount = 0",
        ],
    ),
    "pymongo": (
        "pymongo",
        [
            "mock_{attr} = MagicMock()",
            "mock_{attr}.find_one.return_value = None",
            "mock_{attr}.find.return_value = iter([])",
            "mock_{attr}.insert_one.return_value = MagicMock(inserted_id='mock_id')",
            "mock_{attr}.update_one.return_value = MagicMock(modified_count=1)",
            "mock_{attr}.delete_one.return_value = MagicMock(deleted_count=1)",
        ],
    ),
    "motor": (
        "motor_mongodb",
        [
            "mock_{attr} = AsyncMock()",
            "mock_{attr}.find_one.return_value = None",
            "mock_{attr}.find.return_value = AsyncMock(to_list=AsyncMock(return_value=[]))",
            "mock_{attr}.insert_one.return_value = AsyncMock(inserted_id='mock_id')",
        ],
    ),
    "redis": (
        "redis",
        [
            "mock_{attr} = MagicMock()",
            "mock_{attr}.get.return_value = None",
            "mock_{attr}.set.return_value = True",
            "mock_{attr}.delete.return_value = 1",
            "mock_{attr}.exists.return_value = 0",
        ],
    ),
    "boto3": (
        "boto3",
        [
            "mock_{attr} = MagicMock()",
            "mock_{attr}.Table.return_value.get_item.return_value = {'Item': {}}",
            "mock_{attr}.Table.return_value.put_item.return_value = {}",
            "mock_{attr}.Table.return_value.delete_item.return_value = {}",
            "mock_{attr}.Table.return_value.query.return_value = {'Items': []}",
        ],
    ),
}


def detect_db_mocks_python(deps: list[DepInfo]) -> list[tuple[DepInfo, list[str]]]:
    result = []
    for dep in deps:
        for prefix, (_, templates) in _PYTHON_DB_MOCKS.items():
            if dep.module.startswith(prefix):
                attr = (dep.alias or dep.name).lower()
                lines = [t.format(attr=attr) for t in templates]
                result.append((dep, lines))
                break
    return result


# ── assertion helpers ─────────────────────────────────────────────────────────

_BUILTIN_TYPES = {"dict", "list", "str", "int", "float", "bool", "bytes", "set", "tuple"}

_MAX_TEST_NAME = 80


def _truncate_test_name(name: str) -> str:
    if len(name) <= _MAX_TEST_NAME:
        return name
    parts = name.split("_when", 1)
    if len(parts) == 2:
        prefix, condition = parts
        budget = _MAX_TEST_NAME - len(prefix) - 5
        return f"{prefix}_when{condition[:max(budget, 8)]}"
    return name[:_MAX_TEST_NAME]


_PRIMITIVE_TYPES = {"str", "int", "float", "bool", "bytes"}


def _return_type_assertion(return_type: str) -> str:
    rt = return_type.strip().strip("'\"")
    m = re.match(r"Optional\[(.+)\]$", rt)
    if m:
        base = m.group(1).strip().split("[")[0]
        if base in _PRIMITIVE_TYPES:
            return f"        assert result is None or isinstance(result, {base})"
        return f"        assert result is None or result is not None"
    base = rt.split("[")[0].strip()
    # Only use isinstance for primitives; container types and ORM models will be mocks
    if base in _PRIMITIVE_TYPES:
        return f"        assert isinstance(result, {base})"
    return f"        assert result is not None"


def _infer_literal_return(method: MethodInfo) -> str | None:
    """Scan method body for a dominant literal return and emit an exact assertion."""
    if method.ast_node is None or method.is_void:
        return None
    literal_returns: list[str] = []
    for node in ast.walk(method.ast_node):
        if isinstance(node, ast.Return) and node.value is not None:
            val = node.value
            if isinstance(val, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
                literal_returns.append(ast.unparse(val))
            elif isinstance(val, ast.Constant):
                literal_returns.append(repr(val.value))
            elif isinstance(val, ast.Name) and val.id in ("True", "False", "None"):
                literal_returns.append(val.id)
    if not literal_returns:
        return None
    non_none = [r for r in literal_returns if r != "None"]
    if not non_none:
        return None
    if len(set(non_none)) == 1:
        v = non_none[0]
        if v in ("True", "False"):
            return f"        assert result is {v}"
        return f"        assert result == {v}"
    return None


def _infer_dataclass_assertions(
    return_type: str,
    all_classes: list[ClassInfo],
) -> list[str]:
    rt_base = return_type.split("[")[0].strip().strip("'\"")
    matching = [c for c in all_classes if c.name == rt_base]
    if not matching:
        return [f"        assert isinstance(result, {rt_base})"]
    cls = matching[0]
    lines = [f"        assert isinstance(result, {rt_base})"]
    for attr in list(cls.constructor_dep_map.keys())[:3]:
        lines.append(f"        assert result.{attr} is not None")
    return lines


def _infer_dep_call_assertions(
    method: MethodInfo,
    deps: list[DepInfo],
    ctor_map: dict[str, str],
) -> list[str]:
    """Walk method body for self.dep.method() calls and emit assert_called_once[_with]() lines.

    Also handles indirect calls via local aliases:
        repo = self.repository   →  repo.save(x) treated as self.repository.save(x)
    """
    if not method.ast_node or not deps:
        return ["        # TODO: verify side effects manually"]

    dep_type_to_mock = {dep.name: f"mock_{dep.name.lower()}" for dep in deps}
    attr_to_mock: dict[str, str] = {}
    for attr, dep_type in ctor_map.items():
        if dep_type in dep_type_to_mock:
            attr_to_mock[attr] = dep_type_to_mock[dep_type]
    for dep in deps:
        fallback_attr = dep.alias or dep.name.lower()
        if fallback_attr not in attr_to_mock:
            attr_to_mock[fallback_attr] = f"mock_{dep.name.lower()}"

    # Collect local aliases: local_var = self.dep_attr  →  {local_var: mock_name}
    local_alias_to_mock: dict[str, str] = {}
    for stmt in ast.walk(method.ast_node):
        if (isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Attribute)
                and isinstance(stmt.value.value, ast.Name)
                and stmt.value.value.id == "self"):
            local_var = stmt.targets[0].id
            attr = stmt.value.attr
            if attr in attr_to_mock:
                local_alias_to_mock[local_var] = attr_to_mock[attr]

    def _emit(mock_name: str, called_method: str, node: ast.Call) -> str:
        if node.args or node.keywords:
            is_simple = all(
                isinstance(a, (ast.Name, ast.Constant, ast.Attribute))
                for a in node.args
            )
            if is_simple:
                arg_reprs = [ast.unparse(a) for a in node.args]
                kw_reprs = [f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords]
                all_args_str = ", ".join(arg_reprs + kw_reprs)
                if all_args_str:
                    return (
                        f"        {mock_name}.{called_method}"
                        f".assert_called_once_with({all_args_str})"
                    )
        return f"        {mock_name}.{called_method}.assert_called_once()"

    assertions: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(method.ast_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Pattern A: self.dep_attr.method(...)
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self"):
            attr = func.value.attr
            called_method = func.attr
            mock_name = attr_to_mock.get(attr)
            if mock_name:
                key = f"{mock_name}.{called_method}"
                if key not in seen:
                    seen.add(key)
                    assertions.append(_emit(mock_name, called_method, node))
            continue
        # Pattern B: local_alias.method(...)  where local_alias = self.dep_attr
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in local_alias_to_mock):
            mock_name = local_alias_to_mock[func.value.id]
            called_method = func.attr
            key = f"{mock_name}.{called_method}"
            if key not in seen:
                seen.add(key)
                assertions.append(_emit(mock_name, called_method, node))

    return assertions or ["        # TODO: verify side effects manually"]


# ── patch / mock helpers ──────────────────────────────────────────────────────

def _patch_decorators(deps: list[DepInfo], module_path: str, use_async_mock: bool = False) -> list[str]:
    nc = ", new_callable=AsyncMock" if use_async_mock else ""
    return [f"@patch('{module_path}.{dep.name}'{nc})" for dep in deps]


def _mock_args(deps: list[DepInfo]) -> list[str]:
    return [f"mock_{dep.name.lower()}" for dep in deps]


def _infer_mock_result_attr_setup(
    method: MethodInfo,
    deps: list[DepInfo],
    ctor_map: dict[str, str],
) -> list[str]:
    """Detect `result = await self.dep.method(...)` + `result.attr` patterns.

    Returns setup lines like `mock_dep.dep_method.return_value.attr = None`
    so tests don't trigger unexpected errors from truthy AsyncMock attributes.
    """
    if not method.ast_node:
        return []

    dep_type_to_name = {dep.name: dep.name.lower() for dep in deps}
    attr_to_dep_type = {attr: t for attr, t in ctor_map.items() if t in dep_type_to_name}

    # Find result_var → (mock_arg_name, dep_method_name)
    result_vars: dict[str, tuple[str, str]] = {}
    for node in ast.walk(method.ast_node):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        val = node.value
        if isinstance(val, ast.Await):
            val = val.value
        if not isinstance(val, ast.Call):
            continue
        func = val.func
        if not (isinstance(func, ast.Attribute) and
                isinstance(func.value, ast.Attribute) and
                isinstance(func.value.value, ast.Name) and
                func.value.value.id == "self"):
            continue
        dep_attr = func.value.attr
        dep_method = func.attr
        dep_type = attr_to_dep_type.get(dep_attr)
        if dep_type:
            mock_name = f"mock_{dep_type_to_name[dep_type]}"
            result_vars[target.id] = (mock_name, dep_method)

    if not result_vars:
        return []

    # Find attribute accesses on result_vars (e.g. todo.owner_id, todo.status)
    accessed: dict[tuple[str, str], tuple[str, str]] = {}  # (mock, method) -> set of attrs
    for node in ast.walk(method.ast_node):
        if not isinstance(node, ast.Attribute):
            continue
        if isinstance(node.value, ast.Name) and node.value.id in result_vars:
            key = result_vars[node.value.id]
            accessed.setdefault(key, set()).add(node.attr)  # type: ignore[arg-type]

    # Generate setup lines
    lines = []
    for (mock_name, dep_method), attrs in accessed.items():
        for attr in sorted(attrs):
            lines.append(f"        {mock_name}.{dep_method}.return_value.{attr} = None")
    return lines


# ── test method builder ───────────────────────────────────────────────────────

def build_python_test_method(
    method: MethodInfo,
    branch: BranchCase,
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    captured_result: str | None,
    constructor_dep_map: dict[str, str] | None = None,
    all_classes: list[ClassInfo] | None = None,
    value_type_dep_names: set[str] | None = None,
) -> str:
    use_class_directly = method.is_static or method.is_classmethod
    # For static/classmethod, only patch deps that actually appear in the method body.
    # Instance-injected deps (from ctor_map) are irrelevant — static methods cannot
    # access self.attr, so patching them produces dead mock args.
    if use_class_directly and method.ast_node:
        body_src = ast.unparse(method.ast_node)
        deps = [d for d in deps if d.name in body_src]

    # Exclude value-type deps (enums, constants) — they should be imported, not mocked
    _vtypes = value_type_dep_names or set()
    deps = [d for d in deps if d.name not in _vtypes]

    nd_patches = [f"@patch('{p}')" for p in method.nondeterministic_patches]
    nd_mock_args = [f"mock_{p.replace('.', '_')}" for p in method.nondeterministic_patches]
    decorators = _patch_decorators(deps, module_path, use_async_mock=method.is_async) + nd_patches
    mock_args = _mock_args(deps) + nd_mock_args
    # @patch decorators are applied bottom-up, so args are received in reverse order
    all_args = ["self"] + list(reversed(mock_args))
    db_mock_map: dict[str, list[str]] = {
        dep.name: lines for dep, lines in detect_db_mocks_python(deps)
    }

    if branch.is_happy_path:
        if method.is_void:
            test_name = f"callDependency_when{_camel(method.name)}InvokedWithValidArgs"
        elif method.return_type and method.return_type not in (None, "None"):
            ret_label = method.return_type.split("[")[0].strip("'\"")
            test_name = f"return{ret_label}_when{_camel(method.name)}CalledWithValidArgs"
        else:
            test_name = f"complete_when{_camel(method.name)}CalledWithValidArgs"
    else:
        test_name = branch.test_name

    lines: list[str] = []
    if method.is_async:
        lines.append(f"    @pytest.mark.asyncio")
    for d in decorators:
        lines.append(f"    {d}")
    async_kw = "async " if method.is_async else ""
    lines.append(f"    {async_kw}def test_{test_name}({', '.join(all_args)}):")

    for dep, mock_arg in zip(deps, mock_args):
        if dep.name in db_mock_map:
            for setup_line in db_mock_map[dep.name]:
                lines.append(f"        {setup_line}")
        elif branch.mock_side_effect:
            lines.append(f"        {mock_arg}.side_effect = {branch.mock_side_effect}('mocked error')")
        elif branch.mock_return_override is not None:
            lines.append(f"        {mock_arg}.return_value = {branch.mock_return_override}")
        else:
            lines.append(f"        {mock_arg}.return_value = MagicMock()")

    call_args = ", ".join(
        f"{arg}={branch.input_overrides.get(arg, method.arg_defaults.get(arg, _type_sample(method.arg_types.get(arg))))}"
        for arg in method.args
    )

    if class_name and not use_class_directly:
        ctor_map = constructor_dep_map or {}
        if ctor_map:
            dep_type_to_mock: dict[str, str] = {
                dep.name: mock_arg
                for dep, mock_arg in zip(deps, mock_args[:len(deps)])
            }
            ctor_kwargs = ", ".join(
                f"{attr}={dep_type_to_mock.get(type_name, 'MagicMock()')}"
                for attr, type_name in ctor_map.items()
            )
            lines.append(f"        sut = {class_name}({ctor_kwargs})")
        else:
            lines.append(f"        sut = {class_name}()")
            for dep, mock_arg in zip(deps, mock_args):
                attr = dep.alias or dep.name.lower()
                lines.append(f"        sut.{attr} = {mock_arg}.return_value")
        lines.append(f"")

    lines.append(f"        # When")
    aw = "await " if method.is_async else ""
    if use_class_directly:  # already defined above
        caller = class_name if class_name else method.name
        call_expr = f"{caller}.{method.name}({call_args})"
    elif class_name:
        call_expr = f"sut.{method.name}({call_args})"
    else:
        call_expr = f"{method.name}({call_args})"

    if branch.expected_exception:
        lines.append(f"        # Then")
        if branch.expected_exception_match:
            lines.append(
                f"        with pytest.raises({branch.expected_exception},"
                f" match=r\"{branch.expected_exception_match}\"):"
            )
        else:
            lines.append(f"        with pytest.raises({branch.expected_exception}):")
        lines.append(f"            {aw}{call_expr}")
        return "\n".join(lines)

    if method.is_void:
        lines.append(f"        {aw}{call_expr}")
    else:
        lines.append(f"        result = {aw}{call_expr}")

    lines.append(f"")
    lines.append(f"        # Then")

    if method.is_void:
        for assertion in _infer_dep_call_assertions(method, deps, constructor_dep_map or {}):
            lines.append(assertion)
    elif branch.expected_return == "None":
        lines.append(f"        assert result is None")
    elif branch.expected_return in ("True", "False"):
        lines.append(f"        assert result is {branch.expected_return}")
    elif captured_result is not None and branch.is_happy_path:
        lines.append(f"        assert result == {captured_result}")
    elif branch.is_happy_path:
        literal_assert = _infer_literal_return(method)
        if literal_assert:
            lines.append(literal_assert)
        elif method.return_type and method.return_type not in (None, "None"):
            for a in _infer_dataclass_assertions(method.return_type, all_classes or []):
                lines.append(a)
        else:
            lines.append(f"        assert result is not None  # TODO:CLAUDE_FILL verify exact value")
    elif method.return_type and method.return_type not in (None, "None"):
        lines.append(_return_type_assertion(method.return_type))
    else:
        lines.append(f"        assert result is not None  # TODO:CLAUDE_FILL verify exact value")

    return "\n".join(lines)


# ── methods block generator ───────────────────────────────────────────────────

def generate_methods_block(
    methods: list[MethodInfo],
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    ctor_map: dict[str, str],
    enum_types: dict[str, list[str]],
    target: Path,
    root: Path,
    info_: SourceInfo,
    mode: str = "standard",
    execute_capture: bool = False,
    value_type_dep_names: set[str] | None = None,
) -> list[str]:
    """Generate all test method lines for a list of methods."""
    active = TIER_GENERATORS.get(mode, TIER_GENERATORS["standard"])
    lines: list[str] = []
    all_classes = info_.all_classes

    for method in methods:
        branches = analyze_method_branches(method)

        if mode == "minimal":
            branches = [
                b for b in branches
                if b.expected_exception is not None
                or (b.expected_return is not None and not b.is_happy_path)
                or b.is_happy_path
            ]

        captured = None
        if execute_capture and not method.is_void and not method.is_async:
            captured = try_execute_and_capture(target, root, info_, method)

        def make_body(case: BranchCase, cap: str | None = None) -> str:
            return build_python_test_method(
                method, case, deps, module_path, class_name, cap, ctor_map, all_classes,
                value_type_dep_names=value_type_dep_names,
            )

        for branch in branches:
            lines += ["", make_body(branch, captured)]

        if "null" in active:
            from pyforge.cases.combinatorial import null_combination_cases
            for case in null_combination_cases(method):
                lines += ["", make_body(case)]

        if "enum" in active:
            from pyforge.cases.combinatorial import enum_cases
            for case in enum_cases(method, enum_types):
                lines += ["", make_body(case)]

        if "pairwise" in active:
            from pyforge.cases.combinatorial import pairwise_cases
            for case in pairwise_cases(method):
                lines += ["", make_body(case)]

        if "defaults" in active:
            from pyforge.cases.combinatorial import default_arg_cases
            for case in default_arg_cases(method):
                lines += ["", make_body(case)]

        if "union" in active:
            from pyforge.cases.combinatorial import union_type_cases
            for case in union_type_cases(method):
                lines += ["", make_body(case)]

        if "extreme" in active:
            from pyforge.cases.extreme import extreme_value_cases
            for case in extreme_value_cases(method):
                lines += ["", make_body(case)]

        if "hypothesis" in active:
            hyp = build_hypothesis_test(method, deps, module_path, class_name, ctor_map)
            if hyp:
                lines += ["", hyp]

    return lines


# ── main test file generator ──────────────────────────────────────────────────

def generate_python_test_file(
    target: Path,
    root: Path,
    info_: SourceInfo,
    threshold: int,
    mode: str = "standard",
    execute_capture: bool = False,
) -> str:
    all_methods = [m for c in info_.all_classes for m in c.methods] + info_.module_level_methods
    needs_async = any(m.is_async for m in all_methods)
    needs_async_mock = (
        any(dep.module.startswith("motor") for dep in info_.external_deps)
        or needs_async
    )
    needs_sys = any(
        m.arg_types.get(a, "").split("[")[0].strip() == "int"
        for m in all_methods for a in m.args
    )

    mock_imports = "MagicMock, patch"
    if needs_async_mock:
        mock_imports = "MagicMock, patch, AsyncMock"

    has_hypothesis = (
        TIER_GENERATORS.get(mode, set()).issuperset({"hypothesis"})
        and any(
            m.args and not m.is_void and any(a in m.arg_types for a in m.args)
            for m in all_methods
        )
    )

    import_names = ", ".join(c.name for c in info_.all_classes) or (info_.class_name or "*")

    # Identify external deps that should be imported directly (not mocked/patched):
    # - Enum/constant types: their names appear in method arg_defaults (e.g. "TodoStatus.PENDING")
    # - Exception classes: names ending in Error/Exception — used in raise/except, not services
    default_value_names: set[str] = set()
    for m in all_methods:
        for default_repr in m.arg_defaults.values():
            parts = default_repr.split(".")
            if len(parts) >= 2 and parts[0][0].isupper():
                default_value_names.add(parts[0])
    exception_dep_names = {
        d.name for d in info_.external_deps
        if d.name.endswith("Error") or d.name.endswith("Exception")
    }
    value_type_dep_names = default_value_names | exception_dep_names
    value_type_deps = [d for d in info_.external_deps if d.name in value_type_dep_names]

    imports = [
        "import asyncio",
        "import sys",
        "import pytest",
        f"from unittest.mock import {mock_imports}",
        f"from {info_.module_path} import {import_names}",
    ]
    # Import value-type deps (enums etc.) by their original module path
    by_module: dict[str, list[str]] = {}
    for d in value_type_deps:
        by_module.setdefault(d.module, []).append(d.name)
    for mod, names in by_module.items():
        imports.append(f"from {mod} import {', '.join(sorted(names))}")
    if needs_async:
        imports.append("# pip install pytest-asyncio  (needed for async tests)")
    if has_hypothesis:
        imports += [
            "from hypothesis import given, settings",
            "from hypothesis import strategies as st",
        ]
    imports += ["", ""]

    enum_types = detect_enum_types(target)
    # Import locally-defined enum types referenced in arg defaults
    local_enum_names = [e for e in enum_types if e in default_value_names and e not in import_names]
    if local_enum_names:
        extra = ", ".join(sorted(local_enum_names))
        # Append to the existing module import line
        imports[4] = imports[4] + f", {extra}"

    sections: list[str] = []

    for cls in info_.all_classes:
        sections.append(f"class Test{cls.name}:")
        method_lines = generate_methods_block(
            methods=cls.methods,
            deps=info_.external_deps,
            module_path=info_.module_path,
            class_name=cls.name,
            ctor_map=cls.constructor_dep_map,
            enum_types=enum_types,
            target=target,
            root=root,
            info_=info_,
            mode=mode,
            execute_capture=execute_capture,
            value_type_dep_names=value_type_dep_names,
        )
        if not method_lines:
            sections.append("    pass")
        else:
            sections.extend(method_lines)
        sections.append("")

    if info_.module_level_methods:
        sections.append(f"class Test{target.stem.capitalize()}Functions:")
        method_lines = generate_methods_block(
            methods=info_.module_level_methods,
            deps=info_.external_deps,
            module_path=info_.module_path,
            class_name=None,
            ctor_map={},
            enum_types=enum_types,
            target=target,
            root=root,
            info_=info_,
            mode=mode,
            execute_capture=execute_capture,
            value_type_dep_names=value_type_dep_names,
        )
        sections.extend(method_lines)
        sections.append("")

    return "\n".join(imports) + "\n".join(sections) + "\n"
