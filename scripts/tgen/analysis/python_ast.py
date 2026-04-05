"""Python AST-based source analysis (first-class support)."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

from tgen.models import BranchCase, ClassInfo, DepInfo, MethodInfo, SourceInfo


# ── project detection ─────────────────────────────────────────────────────────

def project_root(target: Path) -> Path:
    r = subprocess.run(
        ["git", "-C", str(target.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return Path(r.stdout.strip()) if r.returncode == 0 else target.parent


def detect_lang(target: Path) -> str:
    ext = target.suffix.lstrip(".")
    langs = {"py": "python"}
    lang = langs.get(ext)
    if not lang:
        raise SystemExit(f"ERROR: Unsupported extension: {target.suffix} — only Python (.py) is supported.")
    return lang


def detect_framework(lang: str, root: Path) -> str:
    if lang == "python":
        return "pytest"
    return "unknown"


# ── stdlib exclusion list ─────────────────────────────────────────────────────

STDLIB_MODULES = {
    "os", "sys", "re", "io", "abc", "ast", "csv", "copy", "json",
    "math", "time", "enum", "uuid", "typing", "decimal", "datetime",
    "pathlib", "logging", "hashlib", "functools", "itertools",
    "collections", "contextlib", "dataclasses", "unittest",
}

SAMPLE_VALUES: dict[str, list[Any]] = {
    "int":   [0, 1, -1],
    "str":   ["", "test", "valid@example.com"],
    "float": [0.0, 1.0, -1.0],
    "bool":  [True, False],
    "bytes": [b"", b"test"],
    "list":  [[], [1, 2, 3]],
    "dict":  [{}, {"key": "value"}],
    "None":  [None],
}


def _type_sample(type_hint: str | None) -> str:
    """Return a sensible sample value string for a given type hint."""
    if not type_hint:
        return "None"
    base = type_hint.split("[")[0].strip()
    samples = SAMPLE_VALUES.get(base)
    return repr(samples[1]) if samples and len(samples) > 1 else "None"


# ── non-deterministic patch detection ─────────────────────────────────────────

_NONDETERMINISTIC_PATTERNS: list[tuple[str, str]] = [
    ("datetime.now",       "datetime.datetime"),
    ("datetime.utcnow",    "datetime.datetime"),
    ("datetime.today",     "datetime.datetime"),
    ("date.today",         "datetime.date"),
    ("random.random",      "random.random"),
    ("random.randint",     "random.randint"),
    ("random.choice",      "random.choice"),
    ("random.uniform",     "random.uniform"),
    ("uuid.uuid4",         "uuid.uuid4"),
    ("uuid.uuid1",         "uuid.uuid1"),
    ("os.environ",         "os.environ"),
    ("os.getenv",          "os.getenv"),
]
_OPEN_CALLS = {"open", "Path.read_text", "Path.write_text", "Path.read_bytes"}


def _detect_nondeterministic_patches(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Scan method body for calls to datetime/random/uuid/os.environ/open."""
    body_src = ast.unparse(node)
    patches: list[str] = []
    seen: set[str] = set()
    for fragment, patch_target in _NONDETERMINISTIC_PATTERNS:
        if fragment in body_src and patch_target not in seen:
            patches.append(patch_target)
            seen.add(patch_target)
    for call in _OPEN_CALLS:
        if call in body_src and "builtins.open" not in seen:
            patches.append("builtins.open")
            seen.add("builtins.open")
            break
    return patches


# ── method / class parsing ────────────────────────────────────────────────────

def _parse_method_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_class_method: bool = False,
) -> MethodInfo:
    """Parse a FunctionDef / AsyncFunctionDef into MethodInfo."""
    deco_names = {ast.unparse(d).split("(")[0] for d in node.decorator_list}
    is_static = "staticmethod" in deco_names
    is_cls = "classmethod" in deco_names

    skip = {"self", "cls"}
    arg_names = [a.arg for a in node.args.args if a.arg not in skip]
    arg_types: dict[str, str] = {}
    for a in node.args.args:
        if a.arg not in skip and a.annotation:
            arg_types[a.arg] = ast.unparse(a.annotation)

    arg_defaults: dict[str, str] = {}
    defaults = node.args.defaults
    if defaults:
        offset = len(arg_names) - len(defaults)
        for i, default in enumerate(defaults):
            if offset + i < len(arg_names):
                arg_defaults[arg_names[offset + i]] = ast.unparse(default)

    ret = ast.unparse(node.returns) if node.returns else None
    is_void = ret in (None, "None")

    raises: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc:
            exc_name = ""
            if isinstance(child.exc, ast.Call):
                exc_name = ast.unparse(child.exc.func)
            elif isinstance(child.exc, ast.Name):
                exc_name = child.exc.id
            if exc_name:
                raises.append(exc_name)

    return MethodInfo(
        name=node.name,
        args=arg_names,
        arg_types=arg_types,
        return_type=ret,
        is_void=is_void,
        is_public=not node.name.startswith("_"),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_static=is_static,
        is_classmethod=is_cls,
        raises=raises,
        arg_defaults=arg_defaults,
        nondeterministic_patches=_detect_nondeterministic_patches(node),
        ast_node=node,
    )


def _parse_constructor_deps(init_node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Return {attr_name: dep_type_name} for self.x = x patterns in __init__."""
    param_type: dict[str, str] = {
        a.arg: ast.unparse(a.annotation)
        for a in init_node.args.args
        if a.arg != "self" and a.annotation
    }
    init_args = {a.arg for a in init_node.args.args if a.arg != "self"}
    dep_map: dict[str, str] = {}
    for stmt in ast.walk(init_node):
        if (isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Attribute)
                and isinstance(stmt.targets[0].value, ast.Name)
                and stmt.targets[0].value.id == "self"
                and isinstance(stmt.value, ast.Name)
                and stmt.value.id in init_args):
            attr = stmt.targets[0].attr
            param = stmt.value.id
            if attr not in dep_map:
                dep_map[attr] = param_type.get(param, param)
    return dep_map


# ── main analysis entry points ────────────────────────────────────────────────

def analyze_python(target: Path, root: Path) -> SourceInfo:
    source = target.read_text()
    tree = ast.parse(source)

    try:
        rel = target.relative_to(root).with_suffix("")
        module_path = ".".join(rel.parts)
    except ValueError:
        module_path = target.stem

    external_deps: list[DepInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            if top not in STDLIB_MODULES:
                for alias in node.names:
                    external_deps.append(DepInfo(
                        module=node.module,
                        name=alias.name,
                        alias=alias.asname,
                    ))

    all_classes: list[ClassInfo] = []
    module_level_methods: list[MethodInfo] = []
    _func_types = (ast.FunctionDef, ast.AsyncFunctionDef)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_methods: list[MethodInfo] = []
            ctor_dep_map: dict[str, str] = {}
            for item in node.body:
                if isinstance(item, _func_types):
                    if item.name.startswith("__") and item.name != "__init__":
                        continue
                    m = _parse_method_node(item, is_class_method=True)
                    if m.name == "__init__":
                        ctor_dep_map = _parse_constructor_deps(item)
                    elif m.is_public:
                        class_methods.append(m)
            bases = [ast.unparse(b) for b in node.bases]
            if not any("Enum" in b for b in bases):
                all_classes.append(ClassInfo(
                    name=node.name,
                    methods=class_methods,
                    constructor_dep_map=ctor_dep_map,
                ))
        elif isinstance(node, _func_types):
            if not node.name.startswith("_"):
                module_level_methods.append(_parse_method_node(node))

    first_class = all_classes[0] if all_classes else None
    class_name = first_class.name if first_class else None
    constructor_dep_map = first_class.constructor_dep_map if first_class else {}
    all_methods = module_level_methods + [m for c in all_classes for m in c.methods]

    return SourceInfo(
        lang="python",
        class_name=class_name,
        methods=[m for m in all_methods if m.is_public],
        external_deps=external_deps,
        module_path=module_path,
        constructor_dep_map=constructor_dep_map,
        all_classes=all_classes,
        module_level_methods=[m for m in module_level_methods if m.is_public],
    )


def detect_enum_types(target: Path) -> dict[str, list[str]]:
    """Return {ClassName: [MEMBER_NAME, ...]} for Enum subclasses defined in the file."""
    try:
        tree = ast.parse(target.read_text())
    except SyntaxError:
        return {}
    result: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            if any("Enum" in b for b in bases):
                members = [
                    t.id
                    for item in node.body
                    if isinstance(item, ast.Assign)
                    for t in item.targets
                    if isinstance(t, ast.Name)
                ]
                if members:
                    result[node.name] = members
    return result
