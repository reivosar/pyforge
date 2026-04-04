#!/usr/bin/env python3
"""Auto test generator — static analysis first, Claude only for void/side-effect methods."""

import argparse
import ast
import importlib.util
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[test-gen] {msg}")


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class BranchCase:
    test_name: str               # e.g. "raiseValueError_whenUserIdIsNegative"
    input_overrides: dict        # arg_name -> repr string  e.g. {"user_id": "-1"}
    mock_side_effect: str | None # exception class name to set as side_effect
    mock_return_override: str | None  # repr to set as return_value
    expected_exception: str | None
    expected_return: str | None  # repr string or None
    is_happy_path: bool


@dataclass
class MethodInfo:
    name: str
    args: list[str]
    arg_types: dict[str, str]   # arg_name -> type hint string
    return_type: str | None
    is_void: bool
    is_public: bool
    is_async: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    raises: list[str] = field(default_factory=list)
    # arg_name -> default repr string (only for args that have defaults)
    arg_defaults: dict[str, str] = field(default_factory=dict)
    # patch targets for non-deterministic stdlib calls detected in this method body
    nondeterministic_patches: list[str] = field(default_factory=list)
    ast_node: Any = field(default=None, repr=False, compare=False)


@dataclass
class DepInfo:
    module: str          # e.g. "app.db.repository"
    name: str            # e.g. "UserRepository"
    alias: str | None    # import alias if any


@dataclass
class ClassInfo:
    name: str
    methods: list[MethodInfo]           # public methods only
    constructor_dep_map: dict[str, str] # {attr: dep_type_name}


@dataclass
class SourceInfo:
    lang: str
    class_name: str | None          # first non-Enum class (backward compat)
    methods: list[MethodInfo]       # all public methods (backward compat)
    external_deps: list[DepInfo]
    module_path: str
    constructor_dep_map: dict[str, str] = field(default_factory=dict)
    all_classes: list[ClassInfo] = field(default_factory=list)
    module_level_methods: list[MethodInfo] = field(default_factory=list)


# ── project detection ─────────────────────────────────────────────────────────

def project_root(target: Path) -> Path:
    r = subprocess.run(
        ["git", "-C", str(target.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return Path(r.stdout.strip()) if r.returncode == 0 else target.parent


def detect_lang(target: Path) -> str:
    return {
        "ts": "typescript", "tsx": "typescript",
        "js": "javascript", "jsx": "javascript",
        "py": "python", "rb": "ruby",
        "go": "go", "java": "java", "rs": "rust",
    }.get(target.suffix.lstrip(".")) or die(f"Unsupported extension: {target.suffix}")


def detect_framework(lang: str, root: Path) -> str:
    pkg = root / "package.json"
    if lang in ("typescript", "javascript"):
        if pkg.exists():
            t = pkg.read_text()
            if "vitest" in t: return "vitest"
            if "jest"   in t: return "jest"
            if "mocha"  in t: return "mocha"
        return "jest"
    if lang == "python":
        return "pytest"
    if lang == "ruby":
        return "rspec" if (root / "spec").is_dir() else "minitest"
    if lang == "go":   return "testing"
    if lang == "java":
        r = subprocess.run(["grep", "-rq", "junit.jupiter", str(root)], capture_output=True)
        return "junit5" if r.returncode == 0 else "junit4"
    return "unknown"


# ── static analysis ───────────────────────────────────────────────────────────

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


# Non-deterministic stdlib call patterns → patch target
_NONDETERMINISTIC_PATTERNS: list[tuple[str, str]] = [
    # (AST-unparse fragment to detect, patch target)
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
    # file I/O
    for call in _OPEN_CALLS:
        if call in body_src and "builtins.open" not in seen:
            patches.append("builtins.open")
            seen.add("builtins.open")
            break
    return patches


def _parse_method_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_class_method: bool = False,
) -> MethodInfo:
    """Parse a FunctionDef / AsyncFunctionDef into MethodInfo."""
    # decorator flags
    deco_names = {ast.unparse(d).split("(")[0] for d in node.decorator_list}
    is_static = "staticmethod" in deco_names
    is_cls = "classmethod" in deco_names

    # args: skip 'self' and 'cls'
    skip = {"self", "cls"}
    arg_names = [a.arg for a in node.args.args if a.arg not in skip]
    arg_types: dict[str, str] = {}
    for a in node.args.args:
        if a.arg not in skip and a.annotation:
            arg_types[a.arg] = ast.unparse(a.annotation)

    # default values: aligned to the tail of args
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


def analyze_python(target: Path, root: Path) -> SourceInfo:
    source = target.read_text()
    tree = ast.parse(source)

    try:
        rel = target.relative_to(root).with_suffix("")
        module_path = ".".join(rel.parts)
    except ValueError:
        module_path = target.stem

    # collect external imports (all levels)
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

    # walk top-level body to separate classes from module-level functions
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
            # skip pure Enum classes (no real methods to test)
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

    # backward-compat: first class and its attrs
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


def analyze_with_regex(target: Path, lang: str, root: Path) -> SourceInfo:
    """Fallback regex-based analysis for non-Python files."""
    source = target.read_text()
    methods: list[MethodInfo] = []
    external_deps: list[DepInfo] = []
    class_name: str | None = None

    if lang in ("typescript", "javascript"):
        # imports: import { Foo } from './foo'
        for m in re.finditer(r"import\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", source):
            names = [n.strip() for n in m.group(1).split(",")]
            mod = m.group(2)
            if not mod.startswith("."):  # external
                for name in names:
                    external_deps.append(DepInfo(module=mod, name=name, alias=None))
        # class
        cm = re.search(r"class\s+(\w+)", source)
        if cm:
            class_name = cm.group(1)
        # methods: public methodName(args): ReturnType
        for m in re.finditer(r"(?:public\s+)?(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*(\w+))?", source):
            name = m.group(1)
            if name in ("constructor", "if", "for", "while", "switch"):
                continue
            ret = m.group(3)
            methods.append(MethodInfo(
                name=name, args=[], arg_types={},
                return_type=ret, is_void=(ret in (None, "void")),
                is_public=True,
            ))

    elif lang == "go":
        for m in re.finditer(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)\s*(?:\(([^)]*)\)|(\w+))?', source):
            name = m.group(1)
            ret = m.group(3) or m.group(4)
            methods.append(MethodInfo(
                name=name, args=[], arg_types={},
                return_type=ret, is_void=(not ret or ret == "error"),
                is_public=name[0].isupper(),
            ))

    elif lang == "java":
        for m in re.finditer(r"public\s+(\w+)\s+(\w+)\s*\(([^)]*)\)", source):
            ret, name = m.group(1), m.group(2)
            methods.append(MethodInfo(
                name=name, args=[], arg_types={},
                return_type=ret, is_void=(ret == "void"),
                is_public=True,
            ))

    elif lang == "ruby":
        for m in re.finditer(r"def\s+(\w+)\s*(?:\(([^)]*)\))?", source):
            name = m.group(1)
            methods.append(MethodInfo(
                name=name, args=[], arg_types={},
                return_type=None, is_void=False,
                is_public=not name.startswith("_"),
            ))

    try:
        rel = target.relative_to(root).with_suffix("")
        module_path = ".".join(rel.parts)
    except ValueError:
        module_path = target.stem

    return SourceInfo(
        lang=lang, class_name=class_name,
        methods=[m for m in methods if m.is_public],
        external_deps=external_deps,
        module_path=module_path,
    )


def analyze_source(target: Path, lang: str, root: Path) -> SourceInfo:
    if lang == "python":
        return analyze_python(target, root)
    return analyze_with_regex(target, lang, root)


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


# ── branch analysis ───────────────────────────────────────────────────────────

def _condition_to_name(cond: ast.expr) -> str:
    """Convert AST condition to a CamelCase when-clause name."""
    # handle common patterns explicitly before fallback
    if isinstance(cond, ast.Compare) and len(cond.ops) == 1:
        left, op, right = cond.left, cond.ops[0], cond.comparators[0]
        left_s = ast.unparse(left).replace(".", "_").replace("self_", "")

        # x is None / x is not None
        if isinstance(right, ast.Constant) and right.value is None:
            if isinstance(op, ast.Is):    return f"{_camel(left_s)}IsNone"
            if isinstance(op, ast.IsNot): return f"{_camel(left_s)}IsNotNone"

        # x == "" / x == 0 / x <= 0 etc.
        if isinstance(right, ast.Constant):
            v = right.value
            op_map = {
                ast.LtE: "IsZeroOrNegative" if v == 0 else f"IsLtEq{v}",
                ast.Lt:  "IsNegative"        if v == 0 else f"IsLt{v}",
                ast.GtE: "IsZeroOrPositive"  if v == 0 else f"IsGtEq{v}",
                ast.Gt:  "IsPositive"         if v == 0 else f"IsGt{v}",
                ast.Eq:  "IsEmpty" if v in ("", [], {}) else f"IsEq{v}",
                ast.NotEq: f"IsNot{v}",
            }
            suffix = op_map.get(type(op), "")
            if suffix:
                return f"{_camel(left_s)}{suffix}"

    # not x (empty / falsy check)
    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        inner = ast.unparse(cond.operand).replace("self.", "")
        return f"{_camel(inner)}IsEmpty"

    # len(x) == 0
    if (isinstance(cond, ast.Compare) and
            isinstance(cond.left, ast.Call) and
            isinstance(cond.left.func, ast.Name) and
            cond.left.func.id == "len"):
        arg_s = ast.unparse(cond.left.args[0]).replace("self.", "") if cond.left.args else "arg"
        return f"{_camel(arg_s)}IsEmpty"

    # fallback: sanitise unparse output
    raw = ast.unparse(cond)
    return _camel(re.sub(r"[^a-zA-Z0-9]", "_", raw))


def _camel(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\s]+", s) if w)


def _condition_to_inputs(cond: ast.expr, arg_types: dict[str, str]) -> dict[str, str]:
    """Derive concrete input overrides that TRIGGER the condition."""
    inputs: dict[str, str] = {}

    if isinstance(cond, ast.Compare) and len(cond.ops) == 1:
        left, op, right = cond.left, cond.ops[0], cond.comparators[0]

        if isinstance(left, ast.Name):
            arg = left.id
            if isinstance(right, ast.Constant):
                v = right.value
                if isinstance(op, ast.LtE) and v == 0:   inputs[arg] = "-1"
                elif isinstance(op, ast.Lt) and v == 0:  inputs[arg] = "-1"
                elif isinstance(op, ast.Eq) and v == 0:  inputs[arg] = "0"
                elif isinstance(op, ast.Eq) and v == "": inputs[arg] = '""'
            if isinstance(right, ast.Constant) and right.value is None:
                if isinstance(op, ast.Is): inputs[arg] = "None"

    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        if isinstance(cond.operand, ast.Name):
            arg = cond.operand.id
            hint = arg_types.get(arg, "")
            if "list" in hint.lower(): inputs[arg] = "[]"
            elif "dict" in hint.lower(): inputs[arg] = "{}"
            elif "str" in hint.lower(): inputs[arg] = '""'
            else: inputs[arg] = "[]"

    if (isinstance(cond, ast.Compare) and
            isinstance(cond.left, ast.Call) and
            isinstance(cond.left.func, ast.Name) and
            cond.left.func.id == "len" and
            cond.left.args and isinstance(cond.left.args[0], ast.Name)):
        if isinstance(cond.ops[0], ast.Eq):
            inputs[cond.left.args[0].id] = "[]"

    return inputs


def _boundary_cases_from_condition(
    cond: ast.expr,
    arg_types: dict[str, str],
    exc_name: str | None,
) -> list[BranchCase]:
    """
    For numeric and string/list-length conditions, generate BranchCases at
    the boundary and just across it.

    Examples:
      if x > 100: raise → generates x=100 (safe side) and x=101 (raises)
      if len(s) > 255: raise → generates s="a"*255 (safe) and s="a"*256 (raises)
    """
    cases: list[BranchCase] = []

    if not isinstance(cond, ast.Compare) or len(cond.ops) != 1:
        return cases

    left, op, right = cond.left, cond.ops[0], cond.comparators[0]

    # ── numeric: arg op N ────────────────────────────────────────────────────
    if (isinstance(left, ast.Name) and
            isinstance(right, ast.Constant) and
            isinstance(right.value, (int, float)) and
            right.value != 0):
        arg, N = left.id, right.value

        # (value, triggers_condition)
        pairs: list[tuple[int | float, bool]] = []
        if   isinstance(op, ast.Gt):  pairs = [(N, False), (N + 1, True)]
        elif isinstance(op, ast.GtE): pairs = [(N - 1, False), (N, True)]
        elif isinstance(op, ast.Lt):  pairs = [(N, False), (N - 1, True)]
        elif isinstance(op, ast.LtE): pairs = [(N + 1, False), (N, True)]

        for val, triggers in pairs:
            label = f"AtBoundary{val}".replace("-", "Minus").replace(".", "Dot")
            if triggers and exc_name:
                cases.append(BranchCase(
                    test_name=f"raise{exc_name}_when{_camel(arg)}Is{label}",
                    input_overrides={arg: repr(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=exc_name, expected_return=None,
                    is_happy_path=False,
                ))
            elif not triggers:
                cases.append(BranchCase(
                    test_name=f"notRaise_when{_camel(arg)}IsOnSafeSide{label}",
                    input_overrides={arg: repr(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=None, expected_return=None,
                    is_happy_path=False,
                ))

    # ── len(arg) op N ────────────────────────────────────────────────────────
    if (isinstance(left, ast.Call) and
            isinstance(left.func, ast.Name) and
            left.func.id == "len" and
            left.args and isinstance(left.args[0], ast.Name) and
            isinstance(right, ast.Constant) and isinstance(right.value, int) and
            right.value > 0):
        arg, N = left.args[0].id, right.value
        hint = arg_types.get(arg, "")
        is_str = "str" in hint.lower()

        def make_len_val(n: int) -> str:
            n = max(0, n)
            return f'"{"a" * n}"' if is_str else f'[0] * {n}'

        pairs_len: list[tuple[int, bool]] = []
        if   isinstance(op, ast.Gt):  pairs_len = [(N, False), (N + 1, True)]
        elif isinstance(op, ast.GtE): pairs_len = [(max(0, N - 1), False), (N, True)]
        elif isinstance(op, ast.Lt):  pairs_len = [(N, False), (max(0, N - 1), True)]
        elif isinstance(op, ast.LtE): pairs_len = [(N + 1, False), (N, True)]
        elif isinstance(op, ast.Eq):  pairs_len = [(max(0, N - 1), False), (N, True), (N + 1, False)]

        for val, triggers in pairs_len:
            label = f"LengthIs{val}"
            if triggers and exc_name:
                cases.append(BranchCase(
                    test_name=f"raise{exc_name}_when{_camel(arg)}{label}",
                    input_overrides={arg: make_len_val(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=exc_name, expected_return=None,
                    is_happy_path=False,
                ))
            elif not triggers:
                cases.append(BranchCase(
                    test_name=f"notRaise_when{_camel(arg)}{label}",
                    input_overrides={arg: make_len_val(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=None, expected_return=None,
                    is_happy_path=False,
                ))

    return cases


def _exc_short(node: ast.expr | None) -> str:
    if node is None: return "Exception"
    if isinstance(node, ast.Call): return ast.unparse(node.func).split(".")[-1]
    return ast.unparse(node).split(".")[-1]


def analyze_method_branches(method: MethodInfo) -> list[BranchCase]:
    """
    Walk a method's AST and produce one BranchCase per distinct execution path:
      - each `if cond: raise X`         → exception case
      - each `if cond: return Y`         → early-return case
      - each `except E: raise X`         → dependency-failure case
      - always appends the happy path    → normal return case
    """
    if method.ast_node is None:
        return [BranchCase("", {}, None, None, None, None, True)]

    node: ast.FunctionDef = method.ast_node
    cases: list[BranchCase] = []

    def walk(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            # ── if / elif / else ──────────────────────────────────────────
            if isinstance(stmt, ast.If):
                cond = stmt.test
                when_name = _condition_to_name(cond)
                inputs = _condition_to_inputs(cond, method.arg_types)

                for child in stmt.body:
                    if isinstance(child, ast.Raise):
                        exc = _exc_short(child.exc)
                        cases.append(BranchCase(
                            test_name=f"raise{exc}_when{when_name}",
                            input_overrides=inputs,
                            mock_side_effect=None,
                            mock_return_override=None,
                            expected_exception=exc,
                            expected_return=None,
                            is_happy_path=False,
                        ))
                        # boundary value cases for numeric / length conditions
                        cases.extend(
                            _boundary_cases_from_condition(cond, method.arg_types, exc)
                        )
                    elif isinstance(child, ast.Return) and child.value is not None:
                        ret_s = ast.unparse(child.value)
                        ret_label = "None" if ret_s == "None" else _camel(
                            re.sub(r"[^a-zA-Z0-9]", "_", ret_s[:24])
                        )
                        cases.append(BranchCase(
                            test_name=f"return{ret_label}_when{when_name}",
                            input_overrides=inputs,
                            mock_side_effect=None,
                            mock_return_override="None" if ret_s == "None" else None,
                            expected_exception=None,
                            expected_return=ret_s,
                            is_happy_path=False,
                        ))

                # recurse into else/elif
                if stmt.orelse:
                    walk(stmt.orelse)

            # ── try / except ──────────────────────────────────────────────
            elif isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    caught = ast.unparse(handler.type) if handler.type else "Exception"
                    caught_short = caught.split(".")[-1]
                    for child in handler.body:
                        if isinstance(child, ast.Raise):
                            raised = _exc_short(child.exc) if child.exc else caught_short
                            cases.append(BranchCase(
                                test_name=f"raise{raised}_whenDependencyRaises{caught_short}",
                                input_overrides={},
                                mock_side_effect=caught_short,
                                mock_return_override=None,
                                expected_exception=raised,
                                expected_return=None,
                                is_happy_path=False,
                            ))

    walk(node.body)

    # happy path always last
    cases.append(BranchCase(
        test_name="",   # filled by caller
        input_overrides={},
        mock_side_effect=None,
        mock_return_override=None,
        expected_exception=None,
        expected_return=None,
        is_happy_path=True,
    ))

    return cases


# ── null-combination / enum-exhaustion / pairwise cases ─────────────────────

def _null_combination_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each nullable arg (Optional[X] or untyped), generate one BranchCase
    with that arg=None and all others at their default sample value.
    Only activates when the method has ≥2 args.
    """
    if len(method.args) < 2:
        return []
    nullable = [
        a for a in method.args
        if not method.arg_types.get(a) or "Optional" in method.arg_types.get(a, "")
    ]
    cases = []
    for null_arg in nullable:
        cases.append(BranchCase(
            test_name=f"raiseOrReturnNone_when{_camel(null_arg)}IsNone",
            input_overrides={null_arg: "None"},
            mock_side_effect=None, mock_return_override=None,
            expected_exception=None, expected_return=None,
            is_happy_path=False,
        ))
    return cases


def _enum_cases(method: MethodInfo, enum_types: dict[str, list[str]]) -> list[BranchCase]:
    """
    For each arg whose type hint names an Enum class in the file,
    generate one BranchCase per enum member.
    """
    cases = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "")
        if hint in enum_types:
            for member in enum_types[hint]:
                cases.append(BranchCase(
                    test_name=f"complete_when{_camel(arg)}Is{member}",
                    input_overrides={arg: f"{hint}.{member}"},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=None, expected_return=None,
                    is_happy_path=False,
                ))
    return cases


def _pairwise_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For methods with ≥3 args, generate the minimum set of test rows that
    covers every (arg_i=v_i, arg_j=v_j) pair using a greedy algorithm.
    Each arg gets 2 candidate values derived from SAMPLE_VALUES / type hints.
    """
    if len(method.args) < 3:
        return []

    args = method.args
    values: dict[str, list[str]] = {}
    for arg in args:
        hint = method.arg_types.get(arg, "")
        base = hint.split("[")[0].strip() if hint else ""
        vs = SAMPLE_VALUES.get(base, [None, "test"])
        v0 = repr(vs[0]) if vs else "None"
        v1 = repr(vs[1]) if len(vs) > 1 else v0
        values[arg] = [v0, v1]

    # build the full set of (arg_i, vi, arg_j, vj) pairs to cover
    uncovered: set[tuple] = set()
    for i in range(len(args)):
        for j in range(i + 1, len(args)):
            for vi in values[args[i]]:
                for vj in values[args[j]]:
                    uncovered.add((args[i], vi, args[j], vj))

    rows: list[dict[str, str]] = []
    while uncovered:
        # greedy: assign each arg value that maximises coverage of remaining pairs
        row: dict[str, str] = {}
        for arg in args:
            best_val, best_score = values[arg][0], -1
            for v in values[arg]:
                score = sum(
                    1 for prev_arg, prev_val in row.items()
                    if (prev_arg, prev_val, arg, v) in uncovered
                    or (arg, v, prev_arg, prev_val) in uncovered
                )
                if score > best_score:
                    best_score, best_val = score, v
            row[arg] = best_val

        newly = {
            (args[i], row[args[i]], args[j], row[args[j]])
            for i in range(len(args))
            for j in range(i + 1, len(args))
        } & uncovered
        if not newly:
            break  # safety: avoid infinite loop if all remaining pairs are degenerate
        uncovered -= newly
        rows.append(dict(row))

    label = "".join(_camel(a) for a in args)
    return [
        BranchCase(
            test_name=f"complete_pairwiseComb{i + 1}_{label}",
            input_overrides=row,
            mock_side_effect=None, mock_return_override=None,
            expected_exception=None, expected_return=None,
            is_happy_path=False,
        )
        for i, row in enumerate(rows)
    ]


def _default_arg_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each arg with a default value, generate:
    - one test using the explicit default (validates the default path)
    - one test with an alternate non-default value if the type suggests one
    """
    if not method.arg_defaults:
        return []
    cases: list[BranchCase] = []
    for arg, default_repr in method.arg_defaults.items():
        arg_label = _camel(arg)
        # test with the default value explicitly supplied
        cases.append(BranchCase(
            test_name=f"complete_when{arg_label}IsDefault{_camel(re.sub(r'[^a-zA-Z0-9]', '_', default_repr[:16]))}",
            input_overrides={arg: default_repr},
            mock_side_effect=None, mock_return_override=None,
            expected_exception=None, expected_return=None,
            is_happy_path=False,
        ))
        # alternate value opposite to the default
        hint = method.arg_types.get(arg, "")
        if "bool" in hint.lower():
            alt = "False" if default_repr.strip() == "True" else "True"
        elif "str" in hint.lower():
            alt = '""' if default_repr.strip() != '""' else '"alt"'
        elif hint.split("[")[0].strip() in ("int", "float"):
            alt = "0" if default_repr.strip() not in ("0", "0.0") else "-1"
        elif "list" in hint.lower():
            alt = "[]" if default_repr.strip() != "[]" else "[1, 2, 3]"
        elif default_repr.strip() == "None":
            alt = _type_sample(hint) if hint else '"value"'
        else:
            alt = None
        if alt and alt != default_repr:
            cases.append(BranchCase(
                test_name=f"complete_when{arg_label}IsNonDefault",
                input_overrides={arg: alt},
                mock_side_effect=None, mock_return_override=None,
                expected_exception=None, expected_return=None,
                is_happy_path=False,
            ))
    return cases


def _parse_union_members(hint: str) -> list[str]:
    """
    Extract member types from Union[X, Y] or X | Y.
    Returns [] if not a union.
    """
    hint = hint.strip()
    # Union[X, Y, ...]
    m = re.match(r"Union\[(.+)\]$", hint)
    if m:
        return [t.strip() for t in m.group(1).split(",")]
    # X | Y (Python 3.10+)
    if "|" in hint and not hint.startswith("Optional"):
        parts = [p.strip() for p in hint.split("|")]
        if len(parts) >= 2:
            return parts
    # Optional[X] ≡ Union[X, None]
    m2 = re.match(r"Optional\[(.+)\]$", hint)
    if m2:
        return [m2.group(1).strip(), "None"]
    return []


def _union_type_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each arg with a Union / Optional / X|Y type hint,
    generate one BranchCase per concrete member type (excluding None — already in null_combination).
    """
    cases: list[BranchCase] = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "")
        members = _parse_union_members(hint)
        concrete = [m for m in members if m not in ("None", "NoneType")]
        if len(concrete) < 2:
            continue  # single-type or no union
        for member in concrete:
            sample = _type_sample(member)
            if sample == "None":
                continue
            cases.append(BranchCase(
                test_name=f"complete_when{_camel(arg)}Is{_camel(member)}",
                input_overrides={arg: sample},
                mock_side_effect=None, mock_return_override=None,
                expected_exception=None, expected_return=None,
                is_happy_path=False,
            ))
    return cases


# Extreme values: (repr_value, unique_label)
_INT_EXTREMES: list[tuple[str, str]] = [
    ("sys.maxsize",         "MaxInt"),
    ("-(sys.maxsize + 1)",  "MinInt"),
    ("0",                   "Zero"),
]
_FLOAT_EXTREMES: list[tuple[str, str]] = [
    ("float('inf')",  "PosInfinity"),
    ("float('-inf')", "NegInfinity"),
    ("float('nan')",  "NaN"),
    ("-0.0",          "NegativeZero"),
]
_STR_EXTREMES: list[tuple[str, str]] = [
    ('""',             "EmptyString"),
    ('"\\x00"',        "NullByte"),
    ('"a" * 10000',    "VeryLongStr"),
    ('"日本語テスト"', "UnicodeStr"),
]


def _extreme_value_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For int/float/str typed args, generate tests at extreme/special values
    that static analysis wouldn't otherwise cover.
    """
    cases: list[BranchCase] = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "").split("[")[0].strip()
        if hint == "int":
            extremes = _INT_EXTREMES
        elif hint == "float":
            extremes = _FLOAT_EXTREMES
        elif hint == "str":
            extremes = _STR_EXTREMES
        else:
            continue
        for val, label in extremes:
            cases.append(BranchCase(
                test_name=f"complete_when{_camel(arg)}Is{label}",
                input_overrides={arg: val},
                mock_side_effect=None, mock_return_override=None,
                expected_exception=None, expected_return=None,
                is_happy_path=False,
            ))
    return cases


# ── db framework detection ────────────────────────────────────────────────────

@dataclass
class DbMockSpec:
    framework: str       # e.g. "sqlalchemy", "typeorm"
    dep_name: str        # matched dep class name e.g. "Session"
    setup_lines: list[str]   # mock setup code lines (lang-specific)
    inject_attr: str | None  # attribute name to inject on sut


# Maps (module_prefix, class_name) → db mock spec builder per language
_PYTHON_DB_MOCKS: dict[str, tuple[str, list[str]]] = {
    # sqlalchemy
    "sqlalchemy": (
        "sqlalchemy_session",
        [
            "mock_{attr} = MagicMock(spec=Session)",
            "mock_{attr}.query.return_value.filter.return_value.first.return_value = MagicMock()",
            "mock_{attr}.query.return_value.filter.return_value.all.return_value = []",
            "mock_{attr}.query.return_value.get.return_value = MagicMock()",
            "mock_{attr}.add.return_value = None",
            "mock_{attr}.commit.return_value = None",
            "mock_{attr}.rollback.return_value = None",
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

_TS_DB_MOCKS: dict[str, list[str]] = {
    "typeorm": [
        "const mock{Name} = {{",
        "  find: jest.fn().mockResolvedValue([]),",
        "  findOne: jest.fn().mockResolvedValue(null),",
        "  findOneBy: jest.fn().mockResolvedValue(null),",
        "  save: jest.fn().mockResolvedValue({{}}),",
        "  create: jest.fn().mockReturnValue({{}}),",
        "  delete: jest.fn().mockResolvedValue({{ affected: 1 }}),",
        "  update: jest.fn().mockResolvedValue({{ affected: 1 }}),",
        "}};",
    ],
    "@prisma/client": [
        "import {{ mockDeep, DeepMockProxy }} from 'jest-mock-extended';",
        "import {{ PrismaClient }} from '@prisma/client';",
        "const mock{Name}: DeepMockProxy<PrismaClient> = mockDeep<PrismaClient>();",
    ],
    "mongoose": [
        "const mock{Name} = {{",
        "  find: jest.fn().mockResolvedValue([]),",
        "  findById: jest.fn().mockResolvedValue(null),",
        "  findOne: jest.fn().mockResolvedValue(null),",
        "  create: jest.fn().mockResolvedValue({{}}),",
        "  findByIdAndUpdate: jest.fn().mockResolvedValue(null),",
        "  findByIdAndDelete: jest.fn().mockResolvedValue(null),",
        "}};",
    ],
    "pg": [
        "const mock{Name} = {{",
        "  query: jest.fn().mockResolvedValue({{ rows: [], rowCount: 0 }}),",
        "  connect: jest.fn().mockResolvedValue(undefined),",
        "  release: jest.fn(),",
        "}};",
    ],
    "redis": [
        "const mock{Name} = {{",
        "  get: jest.fn().mockResolvedValue(null),",
        "  set: jest.fn().mockResolvedValue('OK'),",
        "  del: jest.fn().mockResolvedValue(1),",
        "  exists: jest.fn().mockResolvedValue(0),",
        "}};",
    ],
}

_GO_DB_MOCKS: dict[str, list[str]] = {
    "database/sql": [
        "db, sqlMock, err := sqlmock.New()",
        "if err != nil { t.Fatal(err) }",
        "defer db.Close()",
        "sqlMock.ExpectQuery(...).WillReturnRows(sqlmock.NewRows(...))",
    ],
    "gorm.io/gorm": [
        "db, sqlMock, err := sqlmock.New()",
        "if err != nil { t.Fatal(err) }",
        "gormDB, _ := gorm.Open(postgres.New(postgres.Config{Conn: db}), &gorm.Config{})",
    ],
    "go.mongodb.org/mongo-driver": [
        "// Use mongo-driver mock or spin up testcontainers",
        "mt := mtest.New(t, mtest.NewOptions().ClientType(mtest.Mock))",
        "mt.AddMockResponses(mtest.CreateSuccessResponse())",
    ],
}


def detect_db_mocks_python(deps: list[DepInfo]) -> list[tuple[DepInfo, list[str]]]:
    """Return (dep, setup_lines) for each dep that matches a known DB framework."""
    result = []
    for dep in deps:
        for prefix, (_, templates) in _PYTHON_DB_MOCKS.items():
            if dep.module.startswith(prefix):
                attr = (dep.alias or dep.name).lower()
                lines = [t.format(attr=attr) for t in templates]
                result.append((dep, lines))
                break
    return result


def detect_db_mocks_ts(deps: list[DepInfo]) -> list[tuple[DepInfo, list[str]]]:
    result = []
    for dep in deps:
        for mod_key, templates in _TS_DB_MOCKS.items():
            if mod_key in dep.module:
                name = dep.name
                lines = [t.format(Name=name) for t in templates]
                result.append((dep, lines))
                break
    return result


def detect_db_mocks_go(source_code: str) -> list[str]:
    for mod_key, lines in _GO_DB_MOCKS.items():
        if mod_key in source_code:
            return lines
    return []


# ── execute and capture (Python only) ────────────────────────────────────────

def try_execute_and_capture(
    target: Path, root: Path, info_: SourceInfo, method: MethodInfo
) -> str | None:
    """
    Try to import the module, mock all external deps, call the method,
    and return the captured result as a repr string.
    Returns None if anything fails.
    """
    if info_.lang != "python" or method.is_void or method.is_async:
        return None

    try:
        spec = importlib.util.spec_from_file_location(info_.module_path, target)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(root))

        # build patch list
        patch_targets = [f"{info_.module_path}.{dep.name}" for dep in info_.external_deps]

        with _apply_patches(patch_targets):
            spec.loader.exec_module(mod)
            if info_.class_name:
                cls = getattr(mod, info_.class_name, None)
                if cls is None:
                    return None
                instance = cls.__new__(cls)
                # inject mocks for constructor deps
                for dep in info_.external_deps:
                    attr = dep.alias or dep.name.lower()
                    setattr(instance, attr, MagicMock())
                func = getattr(instance, method.name, None)
            else:
                func = getattr(mod, method.name, None)

            if func is None:
                return None

            # build sample args
            sample_args = {
                arg: _make_sample_value(method.arg_types.get(arg))
                for arg in method.args
            }
            result = func(**sample_args)
            r = repr(result)
            # validate the repr is usable as a Python literal
            try:
                compile(r, "<repr>", "eval")
                return r
            except SyntaxError:
                return None

    except Exception:
        return None
    finally:
        if str(root) in sys.path:
            sys.path.remove(str(root))


def _apply_patches(targets: list[str]):
    """Context manager that patches all given targets."""
    from contextlib import ExitStack
    stack = ExitStack()
    for t in targets:
        try:
            stack.enter_context(patch(t, MagicMock()))
        except Exception:
            pass
    return stack


def _make_sample_value(type_hint: str | None) -> Any:
    if not type_hint:
        return None
    base = type_hint.split("[")[0].strip()
    samples = SAMPLE_VALUES.get(base)
    return samples[1] if samples and len(samples) > 1 else None


# ── test file generation (Python) ─────────────────────────────────────────────

def _patch_decorators(deps: list[DepInfo], module_path: str) -> list[str]:
    return [f"@patch('{module_path}.{dep.name}')" for dep in deps]


def _mock_args(deps: list[DepInfo]) -> list[str]:
    return [f"mock_{dep.name.lower()}" for dep in deps]


def _build_python_test_method(
    method: MethodInfo,
    branch: BranchCase,
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    captured_result: str | None,
    constructor_dep_map: dict[str, str] | None = None,
) -> str:
    # merge regular dep patches + non-deterministic stdlib patches
    nd_patches = [f"@patch('{p}')" for p in method.nondeterministic_patches]
    nd_mock_args = [f"mock_{p.replace('.', '_')}" for p in method.nondeterministic_patches]
    decorators = _patch_decorators(deps, module_path) + nd_patches
    mock_args = _mock_args(deps) + nd_mock_args
    all_args = ["self"] + mock_args
    db_mock_map: dict[str, list[str]] = {
        dep.name: lines for dep, lines in detect_db_mocks_python(deps)
    }

    # resolve test name
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
    lines.append(f"    {async_kw}def {test_name}({', '.join(all_args)}):")

    # mock setup
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

    # build call args — apply input overrides for this branch
    call_args = ", ".join(
        f"{arg}={branch.input_overrides.get(arg, _type_sample(method.arg_types.get(arg)))}"
        for arg in method.args
    )

    # sut instantiation
    use_class_directly = method.is_static or method.is_classmethod
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

    # When
    lines.append(f"        # When")
    aw = "await " if method.is_async else ""
    if use_class_directly:
        # static/classmethod: call directly on the class, no instance needed
        caller = class_name if class_name else method.name
        call_expr = f"{caller}.{method.name}({call_args})"
    elif class_name:
        call_expr = f"sut.{method.name}({call_args})"
    else:
        call_expr = f"{method.name}({call_args})"

    if branch.expected_exception:
        lines.append(f"        # Then")
        lines.append(f"        with pytest.raises({branch.expected_exception}):")
        lines.append(f"            {aw}{call_expr}")
        return "\n".join(lines)

    if method.is_void:
        lines.append(f"        {aw}{call_expr}")
    else:
        lines.append(f"        result = {aw}{call_expr}")

    # Then
    lines.append(f"")
    lines.append(f"        # Then")

    if method.is_void:
        lines.append(f"        # TODO:CLAUDE_FILL verify side effects / mock calls")
    elif branch.expected_return == "None":
        lines.append(f"        assert result is None")
    elif captured_result is not None and branch.is_happy_path:
        lines.append(f"        assert result == {captured_result}")
    elif method.return_type and method.return_type not in (None, "None"):
        lines.append(f"        assert result is not None")
    else:
        lines.append(f"        # TODO:CLAUDE_FILL - add assertion")

    return "\n".join(lines)


def _generate_methods_block(
    methods: list[MethodInfo],
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    ctor_map: dict[str, str],
    enum_types: dict[str, list[str]],
    target: Path,
    root: Path,
    info_: "SourceInfo",
) -> list[str]:
    """Generate all test method lines for a list of methods. Returns list of code lines."""
    lines: list[str] = []
    for method in methods:
        branches = analyze_method_branches(method)
        captured = try_execute_and_capture(target, root, info_, method)

        for branch in branches:
            body = _build_python_test_method(
                method, branch, deps, module_path, class_name, captured, ctor_map,
            )
            lines += ["", body]

        # null combinations (one per nullable arg, 2+ args only)
        for case in _null_combination_cases(method):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # enum exhaustion (one per enum member per typed arg)
        for case in _enum_cases(method, enum_types):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # pairwise (3+ args only)
        for case in _pairwise_cases(method):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # default argument variation
        for case in _default_arg_cases(method):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # Union/Optional type member tests
        for case in _union_type_cases(method):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # extreme / special values (int maxsize, float nan/inf, str unicode/null/long)
        for case in _extreme_value_cases(method):
            body = _build_python_test_method(
                method, case, deps, module_path, class_name, None, ctor_map,
            )
            lines += ["", body]

        # Hypothesis property test (typed args only)
        hyp = _build_hypothesis_test(method, deps, module_path, class_name, ctor_map)
        if hyp:
            lines += ["", hyp]

    return lines


def generate_python_test_file(
    target: Path, root: Path, info_: SourceInfo, threshold: int
) -> str:
    all_methods = [m for c in info_.all_classes for m in c.methods] + info_.module_level_methods
    needs_async = any(m.is_async for m in all_methods)
    needs_async_mock = any(dep.module.startswith("motor") for dep in info_.external_deps)
    needs_sys = any(
        m.arg_types.get(a, "").split("[")[0].strip() == "int"
        for m in all_methods for a in m.args
    )

    mock_imports = "MagicMock, patch"
    if needs_async_mock:
        mock_imports = "MagicMock, patch, AsyncMock"

    has_hypothesis = any(
        m.args and not m.is_void and any(a in m.arg_types for a in m.args)
        for m in all_methods
    )

    # build import names for all source classes
    import_names = ", ".join(
        c.name for c in info_.all_classes
    ) or (info_.class_name or "*")

    imports = [
        "import asyncio",
        "import sys",
        "import pytest",
        f"from unittest.mock import {mock_imports}",
        f"from {info_.module_path} import {import_names}",
    ]
    if needs_async:
        imports.append("# pip install pytest-asyncio  (needed for async tests)")
    if has_hypothesis:
        imports += [
            "from hypothesis import given, settings",
            "from hypothesis import strategies as st",
        ]
    imports += ["", ""]

    enum_types = detect_enum_types(target)
    sections: list[str] = []

    # ── one test class per source class ─────────────────────────────────────
    for cls in info_.all_classes:
        sections.append(f"class Test{cls.name}:")
        method_lines = _generate_methods_block(
            methods=cls.methods,
            deps=info_.external_deps,
            module_path=info_.module_path,
            class_name=cls.name,
            ctor_map=cls.constructor_dep_map,
            enum_types=enum_types,
            target=target,
            root=root,
            info_=info_,
        )
        if not method_lines:
            sections.append("    pass")
        else:
            sections.extend(method_lines)
        sections.append("")

    # ── module-level functions ───────────────────────────────────────────────
    if info_.module_level_methods:
        sections.append(f"class Test{target.stem.capitalize()}Functions:")
        method_lines = _generate_methods_block(
            methods=info_.module_level_methods,
            deps=info_.external_deps,
            module_path=info_.module_path,
            class_name=None,
            ctor_map={},
            enum_types=enum_types,
            target=target,
            root=root,
            info_=info_,
        )
        sections.extend(method_lines)
        sections.append("")

    return "\n".join(imports) + "\n".join(sections) + "\n"


# ── test file generation (non-Python) ─────────────────────────────────────────

def generate_ts_test_file(target: Path, info_: SourceInfo, framework: str) -> str:
    subject = info_.class_name or target.stem
    source = target.read_text()

    db_mocks = detect_db_mocks_ts(info_.external_deps)
    db_dep_names = {dep.name for dep, _ in db_mocks}
    mock_jest_lines = []
    mock_var_lines = []
    for dep in info_.external_deps:
        if dep.name not in db_dep_names:
            mock_jest_lines.append(f"jest.mock('{dep.module}');")
            mock_var_lines.append(
                f"const mock{dep.name} = {dep.name} as jest.Mocked<typeof {dep.name}>;"
            )
    db_setup_lines: list[str] = []
    for _, ls in db_mocks:
        db_setup_lines.extend(ls)
    before_each_body = "\n    ".join([f"sut = new {subject}();"] + db_setup_lines)

    # branch analysis
    branch_map = analyze_branches_regex(source, info_.lang)

    methods_code: list[str] = []
    for method in info_.methods:
        branches = branch_map.get(method.name, [
            BranchCase("", {}, None, None, None, None, True)
        ])
        for branch in branches:
            call_args = ", ".join(_type_sample(None) for _ in method.args)
            if branch.is_happy_path:
                test_name = f"return{method.return_type or 'void'}_{method.name}_whenCalledWithValidArgs"
                then = ("// TODO:CLAUDE_FILL verify mock calls / side effects"
                        if method.is_void else "expect(result).toBeDefined();")
                ret_prefix = "" if method.is_void else "const result = "
                methods_code.append(
                    f"  it('{test_name}', () => {{\n"
                    f"    // When\n"
                    f"    {ret_prefix}sut.{method.name}({call_args});\n\n"
                    f"    // Then\n"
                    f"    {then}\n"
                    f"  }});"
                )
            elif branch.expected_exception:
                methods_code.append(
                    f"  it('{branch.test_name}', () => {{\n"
                    f"    // When / Then\n"
                    f"    expect(() => sut.{method.name}({call_args}))\n"
                    f"      .toThrow({branch.expected_exception});\n"
                    f"  }});"
                )
            elif branch.expected_return == "null":
                methods_code.append(
                    f"  it('{branch.test_name}', () => {{\n"
                    f"    // When\n"
                    f"    const result = sut.{method.name}({call_args});\n\n"
                    f"    // Then\n"
                    f"    expect(result).toBeNull();\n"
                    f"  }});"
                )

    return (
        f"import {{ {subject} }} from './{target.stem}';\n"
        + ("\n".join(mock_jest_lines) + "\n" if mock_jest_lines else "")
        + ("\n".join(mock_var_lines) + "\n" if mock_var_lines else "")
        + f"\ndescribe('{subject}', () => {{\n"
        f"  let sut: {subject};\n\n"
        f"  beforeEach(() => {{\n"
        f"    {before_each_body}\n"
        f"  }});\n\n"
        + "\n\n".join(methods_code) + "\n"
        + "});\n"
    )


def generate_go_test_file(target: Path, info_: SourceInfo) -> str:
    pkg = target.stem
    source_code = target.read_text()

    db_setup = detect_db_mocks_go(source_code)
    db_imports = '\t"github.com/DATA-DOG/go-sqlmock"\n' if db_setup else ""
    db_setup_block = ("\n\t".join(db_setup) + "\n") if db_setup else ""

    branch_map = analyze_branches_regex(source_code, "go")

    methods_code: list[str] = []
    for method in info_.methods:
        if not method.is_public:
            continue
        branches = branch_map.get(method.name, [
            BranchCase("", {}, None, None, None, None, True)
        ])
        for branch in branches:
            if branch.is_happy_path:
                test_name = f"Test{method.name}_WhenCalledWithValidArgs"
                then = ("// TODO:CLAUDE_FILL verify side effects"
                        if method.is_void else
                        'if result == nil { t.Fatal("expected non-nil result") }')
                ret_prefix = "" if method.is_void else "result := "
                methods_code.append(
                    f"func {test_name}(t *testing.T) {{\n"
                    + (f"\t{db_setup_block}" if db_setup_block else "")
                    + f"\t// When\n"
                    f"\t{ret_prefix}{method.name}()\n\n"
                    f"\t// Then\n"
                    f"\t{then}\n"
                    f"}}"
                )
            elif branch.expected_exception == "error":
                test_name = f"Test{method.name}_{_camel(branch.test_name)}"
                methods_code.append(
                    f"func {test_name}(t *testing.T) {{\n"
                    f"\t// When\n"
                    f"\t_, err := {method.name}()\n\n"
                    f"\t// Then\n"
                    f"\tif err == nil {{\n"
                    f'\t\tt.Fatal("expected error, got nil")\n'
                    f"\t}}\n"
                    f"}}"
                )
            elif branch.expected_return == "null":
                test_name = f"Test{method.name}_{_camel(branch.test_name)}"
                methods_code.append(
                    f"func {test_name}(t *testing.T) {{\n"
                    f"\t// When\n"
                    f"\tresult := {method.name}()\n\n"
                    f"\t// Then\n"
                    f"\tif result != nil {{\n"
                    f'\t\tt.Fatal("expected nil result")\n'
                    f"\t}}\n"
                    f"}}"
                )

    imports = f'"testing"\n{db_imports}' if db_imports else '"testing"'
    return (
        f"package {pkg}_test\n\nimport (\n\t{imports}\n)\n\n"
        + "\n\n".join(methods_code) + "\n"
    )


# ── regex branch analysis (TS / Go / Java) ───────────────────────────────────

def _cond_name_from_str(cond: str) -> str:
    """Convert raw condition string to CamelCase when-clause."""
    s = cond.strip()
    replacements = [
        (r"===?\s*null",      "IsNull"),
        (r"===?\s*undefined", "IsUndefined"),
        (r"===?\s*nil",       "IsNil"),
        (r"===?\s*0",         "IsZero"),
        (r"===?\s*\"\"",      "IsEmpty"),
        (r"!==?\s*null",      "IsNotNull"),
        (r"<=\s*0",           "IsZeroOrNegative"),
        (r"<\s*0",            "IsNegative"),
        (r">=\s*0",           "IsZeroOrPositive"),
        (r"err\s*!=\s*nil",   "ErrIsNotNil"),
        (r"==\s*nil",         "IsNil"),
        (r"!\s*(\w+)",        r"\1IsFalsy"),
        (r"\.length\s*===?\s*0", "LengthIsZero"),
        (r"len\((\w+)\)\s*==\s*0", r"\1IsEmpty"),
    ]
    for pat, rep in replacements:
        s = re.sub(pat, rep, s)
    # strip punctuation and CamelCase
    s = re.sub(r"[^a-zA-Z0-9]", "_", s)
    return "".join(w.capitalize() for w in s.split("_") if w)[:60]


def _extract_function_bodies(source: str, lang: str) -> list[tuple[str, str]]:
    """Return [(func_name, body_source), ...] via rough brace-matching."""
    results = []
    if lang in ("typescript", "javascript"):
        sig_pat = re.compile(
            r"(?:async\s+)?(?:public\s+|private\s+|protected\s+)?(?:static\s+)?"
            r"(\w+)\s*\([^)]*\)\s*(?::\s*\S+)?\s*\{"
        )
    elif lang == "go":
        sig_pat = re.compile(r"func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\([^)]*\)\s*[^{]*\{")
    elif lang == "java":
        sig_pat = re.compile(
            r"(?:public|private|protected)\s+(?:static\s+)?(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{"
        )
    else:
        return results

    for m in sig_pat.finditer(source):
        name = m.group(1)
        if name in ("if", "for", "while", "switch", "catch", "try"):
            continue
        start = m.end() - 1  # position of '{'
        depth, i = 0, start
        while i < len(source):
            if source[i] == "{":   depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    results.append((name, source[start:i+1]))
                    break
            i += 1
    return results


def _boundary_cases_regex(cond_s: str, exc_name: str | None) -> list[BranchCase]:
    """
    Generate boundary BranchCases from a raw condition string (TS/Go/Java).
    Handles patterns like: x > 100, x.length > 255, x >= 0, x < N
    """
    cases: list[BranchCase] = []

    # ── numeric: varName op N ─────────────────────────────────────────────────
    m = re.match(r"(\w+)\s*(>|>=|<|<=|===|==|!==|!=)\s*(-?\d+(?:\.\d+)?)", cond_s.strip())
    if m:
        arg, op_s, n_s = m.group(1), m.group(2), m.group(3)
        N = float(n_s) if "." in n_s else int(n_s)
        if N != 0:
            pairs: list[tuple[int | float, bool]] = []
            if   op_s in (">",  ):  pairs = [(N, False), (N + 1, True)]
            elif op_s in (">=", ):  pairs = [(N - 1, False), (N, True)]
            elif op_s in ("<",  ):  pairs = [(N, False), (N - 1, True)]
            elif op_s in ("<=", ):  pairs = [(N + 1, False), (N, True)]

            for val, triggers in pairs:
                label = str(val).replace("-", "Minus").replace(".", "Dot")
                if triggers and exc_name:
                    cases.append(BranchCase(
                        test_name=f"throw{exc_name}_when{_camel(arg)}IsAtBoundary{label}",
                        input_overrides={arg: str(val)},
                        mock_side_effect=None, mock_return_override=None,
                        expected_exception=exc_name, expected_return=None,
                        is_happy_path=False,
                    ))
                elif not triggers:
                    cases.append(BranchCase(
                        test_name=f"notThrow_when{_camel(arg)}IsOnSafeSide{label}",
                        input_overrides={arg: str(val)},
                        mock_side_effect=None, mock_return_override=None,
                        expected_exception=None, expected_return=None,
                        is_happy_path=False,
                    ))

    # ── string/array length: x.length op N / len(x) op N ────────────────────
    m2 = re.match(
        r"(?:(\w+)\.length|len\((\w+)\))\s*(>|>=|<|<=|===|==)\s*(\d+)",
        cond_s.strip()
    )
    if m2:
        arg = m2.group(1) or m2.group(2)
        op_s, N = m2.group(3), int(m2.group(4))
        if N > 0:
            pairs_len: list[tuple[int, bool]] = []
            if   op_s in (">",         ): pairs_len = [(N, False), (N + 1, True)]
            elif op_s in (">=",        ): pairs_len = [(max(0, N - 1), False), (N, True)]
            elif op_s in ("<",         ): pairs_len = [(N, False), (max(0, N - 1), True)]
            elif op_s in ("<=",        ): pairs_len = [(N + 1, False), (N, True)]
            elif op_s in ("===", "==", ): pairs_len = [(max(0, N - 1), False), (N, True), (N + 1, False)]

            for val, triggers in pairs_len:
                label = f"LengthIs{val}"
                # generic value — test framework fills in actual string/array
                val_hint = f'"{"a" * val}"'
                if triggers and exc_name:
                    cases.append(BranchCase(
                        test_name=f"throw{exc_name}_when{_camel(arg)}{label}",
                        input_overrides={arg: val_hint},
                        mock_side_effect=None, mock_return_override=None,
                        expected_exception=exc_name, expected_return=None,
                        is_happy_path=False,
                    ))
                elif not triggers:
                    cases.append(BranchCase(
                        test_name=f"notThrow_when{_camel(arg)}{label}",
                        input_overrides={arg: val_hint},
                        mock_side_effect=None, mock_return_override=None,
                        expected_exception=None, expected_return=None,
                        is_happy_path=False,
                    ))

    return cases


def analyze_branches_regex(source: str, lang: str) -> dict[str, list[BranchCase]]:
    """
    Returns {func_name: [BranchCase, ...]} for TS/Go/Java.
    Detects throw/return-null in if-blocks and catch-rethrow patterns.
    """
    result: dict[str, list[BranchCase]] = {}
    bodies = _extract_function_bodies(source, lang)

    for func_name, body in bodies:
        cases: list[BranchCase] = []

        # ── if (...) { throw new Exc / return null } ─────────────────────────
        for m in re.finditer(
            r"if\s*\(([^)]+)\)\s*\{([^}]*)\}", body, re.DOTALL
        ):
            cond_s, block = m.group(1).strip(), m.group(2)
            when = _cond_name_from_str(cond_s)

            # throw new Exception(...)
            for tm in re.finditer(r"throw\s+new\s+(\w+)", block):
                exc = tm.group(1)
                cases.append(BranchCase(
                    test_name=f"throw{exc}_when{when}",
                    input_overrides={}, mock_side_effect=None,
                    mock_return_override=None,
                    expected_exception=exc, expected_return=None,
                    is_happy_path=False,
                ))
                # boundary value cases from condition string
                cases.extend(_boundary_cases_regex(cond_s, exc))

            # return null / return nil / return undefined
            if re.search(r"return\s+(?:null|nil|undefined|None)", block):
                cases.append(BranchCase(
                    test_name=f"returnNull_when{when}",
                    input_overrides={}, mock_side_effect=None,
                    mock_return_override="null",
                    expected_exception=None, expected_return="null",
                    is_happy_path=False,
                ))
                cases.extend(_boundary_cases_regex(cond_s, None))

        # ── try { } catch (e) { throw } ──────────────────────────────────────
        for m in re.finditer(
            r"catch\s*\((\w+)(?::\s*\w+)?\)\s*\{([^}]*)\}", body, re.DOTALL
        ):
            caught, handler = m.group(1), m.group(2)
            for tm in re.finditer(r"throw\s+(?:new\s+)?(\w+)", handler):
                raised = tm.group(1)
                cases.append(BranchCase(
                    test_name=f"throw{raised}_whenDependencyThrows",
                    input_overrides={}, mock_side_effect=caught,
                    mock_return_override=None,
                    expected_exception=raised, expected_return=None,
                    is_happy_path=False,
                ))

        # ── Go: if err != nil / if x == nil ──────────────────────────────────
        if lang == "go":
            for m in re.finditer(r"if\s+(err\s*!=\s*nil|(\w+)\s*==\s*nil)\s*\{([^}]*)\}", body, re.DOTALL):
                cond_s, block = m.group(1), m.group(3)
                when = _cond_name_from_str(cond_s)
                if "return" in block:
                    cases.append(BranchCase(
                        test_name=f"returnError_when{when}",
                        input_overrides={}, mock_side_effect="error",
                        mock_return_override=None,
                        expected_exception="error", expected_return=None,
                        is_happy_path=False,
                    ))

        # happy path always last
        cases.append(BranchCase(
            test_name="", input_overrides={}, mock_side_effect=None,
            mock_return_override=None, expected_exception=None,
            expected_return=None, is_happy_path=True,
        ))
        result[func_name] = cases

    return result


# ── hypothesis integration ────────────────────────────────────────────────────

TYPE_TO_STRATEGY: dict[str, str] = {
    "int":           "st.integers()",
    "float":         "st.floats(allow_nan=False, allow_infinity=False)",
    "str":           "st.text()",
    "bool":          "st.booleans()",
    "bytes":         "st.binary()",
    "list":          "st.lists(st.integers())",
    "list[int]":     "st.lists(st.integers())",
    "list[str]":     "st.lists(st.text())",
    "list[float]":   "st.lists(st.floats(allow_nan=False))",
    "dict":          "st.dictionaries(st.text(), st.text())",
    "dict[str,str]": "st.dictionaries(st.text(), st.text())",
    "Optional[int]": "st.one_of(st.none(), st.integers())",
    "Optional[str]": "st.one_of(st.none(), st.text())",
    "Optional[float]": "st.one_of(st.none(), st.floats(allow_nan=False))",
    "EmailStr":      "st.emails()",
    "HttpUrl":       'st.just("https://example.com")',
    "UUID":          "st.uuids().map(str)",
    "date":          "st.dates()",
    "datetime":      "st.datetimes()",
    "Decimal":       "st.decimals(allow_nan=False, allow_infinity=False)",
}


def _type_to_strategy(type_hint: str | None) -> str:
    if not type_hint:
        return "st.none()"
    # normalise: remove spaces inside brackets
    norm = re.sub(r"\s+", "", type_hint)
    if norm in TYPE_TO_STRATEGY:
        return TYPE_TO_STRATEGY[norm]
    # Optional[X] generic
    m = re.match(r"Optional\[(.+)\]", norm)
    if m:
        inner = _type_to_strategy(m.group(1))
        return f"st.one_of(st.none(), {inner})"
    # list[X] generic
    m = re.match(r"[Ll]ist\[(.+)\]", norm)
    if m:
        inner = _type_to_strategy(m.group(1))
        return f"st.lists({inner})"
    return "st.none()"


def _build_hypothesis_test(
    method: MethodInfo,
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    constructor_dep_map: dict[str, str] | None = None,
) -> str | None:
    """
    Return a @given-based property test for the method, or None if
    type hints are insufficient to generate strategies.
    """
    if not method.args or method.is_void:
        return None
    # require at least one typed arg
    typed = {a: method.arg_types[a] for a in method.args if a in method.arg_types}
    if not typed:
        return None

    decorators = _patch_decorators(deps, module_path)
    mock_args = _mock_args(deps)

    given_kwargs = ", ".join(
        f"{arg}={_type_to_strategy(method.arg_types.get(arg))}"
        for arg in method.args
    )
    all_args = ["self"] + mock_args + list(method.args)
    test_name = f"neverRaiseUnexpectedException_when{_camel(method.name)}CalledWithAnyInput"

    lines: list[str] = []
    lines.append(f"    @given({given_kwargs})")
    for d in decorators:
        lines.append(f"    {d}")
    lines.append(f"    @settings(max_examples=50)")
    lines.append(f"    def {test_name}({', '.join(all_args)}):")
    for mock_arg in mock_args:
        lines.append(f"        {mock_arg}.return_value = MagicMock()")
    if class_name:
        ctor_map = constructor_dep_map or {}
        if ctor_map:
            dep_type_to_mock = {dep.name: ma for dep, ma in zip(deps, mock_args)}
            ctor_kwargs = ", ".join(
                f"{attr}={dep_type_to_mock.get(t, 'MagicMock()')}"
                for attr, t in ctor_map.items()
            )
            lines.append(f"        sut = {class_name}({ctor_kwargs})")
        else:
            lines.append(f"        sut = {class_name}()")
            for dep, mock_arg in zip(deps, mock_args):
                attr = dep.alias or dep.name.lower()
                lines.append(f"        sut.{attr} = {mock_arg}.return_value")

    call_args = ", ".join(f"{a}={a}" for a in method.args)
    expected_excs = ", ".join(method.raises) if method.raises else "Exception"
    aw = "await " if method.is_async else ""
    lines.append(f"        # When — property: must never raise unexpected exceptions")
    lines.append(f"        try:")
    if class_name:
        lines.append(f"            {aw}sut.{method.name}({call_args})")
    else:
        lines.append(f"            {aw}{method.name}({call_args})")
    if method.raises:
        lines.append(f"        except ({expected_excs}):")
        lines.append(f"            pass  # expected exceptions are acceptable")
    lines.append(f"        except Exception as e:")
    lines.append(f"            raise AssertionError(f'Unexpected exception: {{type(e).__name__}}: {{e}}')")

    return "\n".join(lines)


def generate_test_file(
    target: Path, root: Path, info_: SourceInfo, framework: str, threshold: int
) -> str:
    if info_.lang == "python":
        return generate_python_test_file(target, root, info_, threshold)
    if info_.lang in ("typescript", "javascript"):
        return generate_ts_test_file(target, info_, framework)
    if info_.lang == "go":
        return generate_go_test_file(target, info_)
    # fallback: delegate to Claude
    return ""


# ── api endpoint detection & test generation ─────────────────────────────────

@dataclass
class ApiEndpoint:
    method: str          # GET POST PUT DELETE PATCH
    path: str            # e.g. "/users/{user_id}"
    handler: str         # function/method name
    path_params: list[str]   # e.g. ["user_id"]
    query_params: list[str]
    has_body: bool       # POST/PUT/PATCH usually have body
    has_auth: bool       # detected from decorator or dependency
    response_model: str | None


# ── API framework detection ───────────────────────────────────────────────────

def detect_api_framework(source: str, lang: str, root: Path) -> str | None:
    """Return the API framework name if the file contains route definitions."""
    if lang == "python":
        if re.search(r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(", source): return "fastapi"
        if re.search(r"@(?:app|bp)\.route\s*\(", source): return "flask"
        if re.search(r"urlpatterns\s*=", source): return "django"
    if lang in ("typescript", "javascript"):
        if "@Controller" in source or "@Get(" in source: return "nestjs"
        if re.search(r"router\.(get|post|put|delete|patch)\s*\(", source): return "express"
        if re.search(r"fastify\.(get|post|put|delete|patch)\s*\(", source): return "fastify"
    if lang == "go":
        if "gin.New()" in source or "gin.Default()" in source: return "gin"
        if "echo.New()" in source: return "echo"
        if "http.HandleFunc" in source or "mux.HandleFunc" in source: return "net/http"
    if lang == "java":
        if "@RestController" in source or "@Controller" in source: return "spring"
    if lang == "ruby":
        if re.search(r"def\s+(index|show|create|update|destroy)", source): return "rails"
    return None


def _extract_path_params(path: str) -> list[str]:
    # FastAPI/Flask: {param}, Express: :param
    return re.findall(r"\{(\w+)\}|:(\w+)", path) and \
           [m[0] or m[1] for m in re.findall(r"\{(\w+)\}|:(\w+)", path)] or []


def detect_api_endpoints(source: str, lang: str, api_framework: str) -> list[ApiEndpoint]:
    endpoints: list[ApiEndpoint] = []

    if lang == "python" and api_framework == "fastapi":
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                m = re.match(r"(?:app|router)\.(get|post|put|delete|patch)",
                             ast.unparse(deco).split("(")[0])
                if not m:
                    continue
                http_method = m.group(1).upper()
                # extract path from decorator
                path = "/"
                if isinstance(deco, ast.Call) and deco.args:
                    path = ast.unparse(deco.args[0]).strip("'\"")
                path_params = _extract_path_params(path)
                has_auth = any(
                    "Depends" in ast.unparse(a) and "auth" in ast.unparse(a).lower()
                    for a in (deco.args + deco.keywords if isinstance(deco, ast.Call) else [])
                ) or any(
                    "token" in ast.unparse(a).lower() or "current_user" in ast.unparse(a).lower()
                    for a in node.args.args
                )
                response_model = None
                if isinstance(deco, ast.Call):
                    for kw in deco.keywords:
                        if kw.arg == "response_model":
                            response_model = ast.unparse(kw.value)
                endpoints.append(ApiEndpoint(
                    method=http_method, path=path, handler=node.name,
                    path_params=path_params, query_params=[],
                    has_body=http_method in ("POST", "PUT", "PATCH"),
                    has_auth=has_auth, response_model=response_model,
                ))

    elif lang == "python" and api_framework == "flask":
        for m in re.finditer(
            r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:[^)]*methods\s*=\s*\[([^\]]*)\])?[^)]*\)\s*\ndef\s+(\w+)",
            source, re.MULTILINE,
        ):
            path = m.group(1)
            methods_raw = m.group(2) or "GET"
            handler = m.group(3)
            for http_method in re.findall(r"[A-Z]+", methods_raw):
                endpoints.append(ApiEndpoint(
                    method=http_method, path=path, handler=handler,
                    path_params=_extract_path_params(path), query_params=[],
                    has_body=http_method in ("POST", "PUT", "PATCH"),
                    has_auth=False, response_model=None,
                ))

    elif lang in ("typescript", "javascript") and api_framework == "express":
        for m in re.finditer(
            r"router\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
            source, re.IGNORECASE,
        ):
            http_method = m.group(1).upper()
            path = m.group(2)
            endpoints.append(ApiEndpoint(
                method=http_method, path=path, handler=path,
                path_params=_extract_path_params(path), query_params=[],
                has_body=http_method in ("POST", "PUT", "PATCH"),
                has_auth="auth" in source.lower(), response_model=None,
            ))

    elif lang in ("typescript", "javascript") and api_framework == "nestjs":
        for m in re.finditer(
            r"@(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]?([^'\")\s]*)['\"]?\s*\)\s*\n\s*(?:async\s+)?(\w+)",
            source,
        ):
            http_method = m.group(1).upper()
            path = m.group(2) or "/"
            handler = m.group(3)
            endpoints.append(ApiEndpoint(
                method=http_method, path=path, handler=handler,
                path_params=_extract_path_params(path), query_params=[],
                has_body=http_method in ("POST", "PUT", "PATCH"),
                has_auth="@UseGuards" in source or "JwtAuthGuard" in source,
                response_model=None,
            ))

    elif lang == "go" and api_framework in ("gin", "echo", "net/http"):
        pat = {
            "gin":      r'r\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"',
            "echo":     r'e\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"',
            "net/http": r'(?:http\.HandleFunc|mux\.HandleFunc)\s*\(\s*"([^"]+)"',
        }[api_framework]
        for m in re.finditer(pat, source):
            if api_framework == "net/http":
                path, http_method = m.group(1), "GET"
            else:
                http_method, path = m.group(1), m.group(2)
            endpoints.append(ApiEndpoint(
                method=http_method, path=path, handler=path,
                path_params=_extract_path_params(path), query_params=[],
                has_body=http_method in ("POST", "PUT", "PATCH"),
                has_auth=False, response_model=None,
            ))

    elif lang == "java" and api_framework == "spring":
        for m in re.finditer(
            r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)"
            r"\s*(?:\(\s*(?:value\s*=\s*)?['\"]([^'\"]*)['\"])?",
            source,
        ):
            method_map = {
                "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
                "DeleteMapping": "DELETE", "PatchMapping": "PATCH", "RequestMapping": "GET",
            }
            http_method = method_map.get(m.group(1), "GET")
            path = m.group(2) or "/"
            endpoints.append(ApiEndpoint(
                method=http_method, path=path, handler=path,
                path_params=_extract_path_params(path), query_params=[],
                has_body=http_method in ("POST", "PUT", "PATCH"),
                has_auth="@PreAuthorize" in source or "@Secured" in source,
                response_model=None,
            ))

    return endpoints


# ── API test generation ───────────────────────────────────────────────────────

def _api_test_cases(ep: ApiEndpoint) -> list[tuple[str, str, int, str]]:
    """Return (test_name, description, expected_status, setup_hint) per case."""
    cases = []
    path_label = re.sub(r"[^a-zA-Z0-9]", "_", ep.path).strip("_")
    handler = _camel(ep.handler or path_label)

    # happy path
    cases.append((
        f"return{ep.response_model or 'Ok'}_when{handler}CalledWithValidInput",
        "valid request",
        200 if ep.method != "POST" else 201,
        "valid",
    ))

    # path param → 404
    if ep.path_params:
        cases.append((
            f"return404_when{handler}CalledWithNonexistentId",
            "non-existent resource",
            404,
            "nonexistent",
        ))

    # body / query validation → 422 / 400
    if ep.has_body:
        cases.append((
            f"return422_when{handler}CalledWithInvalidBody",
            "invalid request body (missing required fields)",
            422,
            "invalid_body",
        ))

    # auth → 401
    if ep.has_auth:
        cases.append((
            f"return401_when{handler}CalledWithoutAuthToken",
            "missing or invalid auth token",
            401,
            "no_auth",
        ))

    # dependency failure → 500
    cases.append((
        f"return500_when{handler}DependencyFails",
        "internal dependency (DB/service) raises exception",
        500,
        "dep_failure",
    ))

    return cases


def generate_api_test_python(
    target: Path, endpoints: list[ApiEndpoint], api_framework: str, module_path: str
) -> str:
    if api_framework == "fastapi":
        client_import = "from fastapi.testclient import TestClient"
        client_setup = f"from {module_path} import app\nclient = TestClient(app)"
    else:  # flask
        client_import = ""
        client_setup = f"from {module_path} import app\nclient = app.test_client()"

    lines = [
        "import pytest",
        client_import,
        "from unittest.mock import patch, MagicMock",
        "",
        client_setup,
        "",
        "",
    ]

    for ep in endpoints:
        lines.append(f"# ── {ep.method} {ep.path} ──────────────────────────────────────")
        lines.append(f"class Test{_camel(ep.handler or ep.path.replace('/', '_'))}:")

        for test_name, desc, status, setup in _api_test_cases(ep):
            # build sample path
            sample_path = ep.path
            for p in ep.path_params:
                sample_path = re.sub(r"\{" + p + r"\}", "1", sample_path)

            lines.append(f"")
            lines.append(f"    def {test_name}(self):")
            lines.append(f"        # When — {desc}")

            if setup == "valid":
                if ep.method == "GET":
                    lines.append(f"        response = client.get('{sample_path}')")
                elif ep.method == "POST":
                    lines.append(f"        response = client.post('{sample_path}', json={{}})")
                elif ep.method == "PUT":
                    lines.append(f"        response = client.put('{sample_path}', json={{}})")
                elif ep.method == "DELETE":
                    lines.append(f"        response = client.delete('{sample_path}')")
                elif ep.method == "PATCH":
                    lines.append(f"        response = client.patch('{sample_path}', json={{}})")
            elif setup == "nonexistent":
                lines.append(f"        response = client.{ep.method.lower()}('{re.sub(chr(123) + '|'.join(ep.path_params) + chr(125), '999999', ep.path)}')")
            elif setup == "invalid_body":
                lines.append(f"        response = client.post('{sample_path}', json=None)")
            elif setup == "no_auth":
                lines.append(f"        # When — call without Authorization header")
                lines.append(f"        response = client.{ep.method.lower()}('{sample_path}')")
            elif setup == "dep_failure":
                lines.append(f"        with patch('TODO:CLAUDE_FILL dependency path') as mock_dep:")
                lines.append(f"            mock_dep.side_effect = Exception('service unavailable')")
                lines.append(f"            response = client.{ep.method.lower()}('{sample_path}')")

            lines.append(f"")
            lines.append(f"        # Then")
            lines.append(f"        assert response.status_code == {status}")
            if status in (200, 201):
                lines.append(f"        assert response.json() is not None")

        lines.append(f"")

    return "\n".join(lines)


def generate_api_test_ts(target: Path, endpoints: list[ApiEndpoint], api_framework: str) -> str:
    lines = [
        "import request from 'supertest';",
        "import { app } from './app';",
        "",
        f"describe('{target.stem} API', () => {{",
    ]

    for ep in endpoints:
        lines.append(f"  // {ep.method} {ep.path}")
        lines.append(f"  describe('{ep.method} {ep.path}', () => {{")

        for test_name, desc, status, setup in _api_test_cases(ep):
            sample_path = re.sub(r":(\w+)", "1", ep.path)
            for p in ep.path_params:
                sample_path = re.sub(r"\{" + p + r"\}", "1", sample_path)

            method_call = ep.method.lower()
            body = ".send({})" if ep.has_body and setup == "valid" else ""
            auth = ".set('Authorization', 'Bearer test-token')" if ep.has_auth and setup != "no_auth" else ""

            lines.append(f"    it('{test_name}', async () => {{")
            lines.append(f"      // When — {desc}")
            lines.append(f"      const response = await request(app)")
            lines.append(f"        .{method_call}('{sample_path}')")
            if auth: lines.append(f"        {auth}")
            if body: lines.append(f"        {body}")
            lines.append(f";")
            lines.append(f"")
            lines.append(f"      // Then")
            lines.append(f"      expect(response.status).toBe({status});")
            if status in (200, 201):
                lines.append(f"      expect(response.body).toBeDefined();")
            lines.append(f"    }});")

        lines.append(f"  }});")

    lines.append("});")
    return "\n".join(lines)


def generate_api_test_go(target: Path, endpoints: list[ApiEndpoint], api_framework: str) -> str:
    pkg = target.stem
    lines = [
        f"package {pkg}_test",
        "",
        'import (',
        '\t"net/http"',
        '\t"net/http/httptest"',
        '\t"testing"',
        ')',
        "",
    ]

    for ep in endpoints:
        sample_path = re.sub(r":(\w+)|\{(\w+)\}", "1", ep.path)
        for test_name, desc, status, _ in _api_test_cases(ep):
            lines.append(f"func Test{_camel(test_name)}(t *testing.T) {{")
            lines.append(f"\t// When — {desc}")
            lines.append(f'\treq := httptest.NewRequest("{ep.method}", "{sample_path}", nil)')
            lines.append(f"\tw := httptest.NewRecorder()")
            lines.append(f"\t// TODO: pass req/w to your handler or router")
            lines.append(f"")
            lines.append(f"\t// Then")
            lines.append(f"\tif w.Code != {status} {{")
            lines.append(f'\t\tt.Errorf("expected {status}, got %d", w.Code)')
            lines.append(f"\t}}")
            lines.append(f"}}")
            lines.append("")

    return "\n".join(lines)


def generate_api_test_java(target: Path, endpoints: list[ApiEndpoint]) -> str:
    class_name = target.stem
    methods = []

    for ep in endpoints:
        sample_path = re.sub(r"\{(\w+)\}", "1", ep.path)
        for test_name, desc, status, _ in _api_test_cases(ep):
            method_call = {
                "GET": f'mockMvc.perform(get("{sample_path}"))',
                "POST": f'mockMvc.perform(post("{sample_path}").contentType(MediaType.APPLICATION_JSON).content("{{}}"))',
                "PUT": f'mockMvc.perform(put("{sample_path}").contentType(MediaType.APPLICATION_JSON).content("{{}}"))',
                "DELETE": f'mockMvc.perform(delete("{sample_path}"))',
                "PATCH": f'mockMvc.perform(patch("{sample_path}").contentType(MediaType.APPLICATION_JSON).content("{{}}"))',
            }.get(ep.method, f'mockMvc.perform(get("{sample_path}"))')

            methods.append(
                f"    @Test\n"
                f"    void {test_name}() throws Exception {{\n"
                f"        // When — {desc}\n"
                f"        {method_call}\n"
                f"            // Then\n"
                f"            .andExpect(status().is({status}));\n"
                f"    }}"
            )

    return (
        "import org.junit.jupiter.api.Test;\n"
        "import org.springframework.beans.factory.annotation.Autowired;\n"
        "import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;\n"
        "import org.springframework.test.web.servlet.MockMvc;\n"
        "import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;\n"
        "import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;\n"
        "\n"
        f"@WebMvcTest({class_name}.class)\n"
        f"class {class_name}Test {{\n"
        "\n"
        "    @Autowired\n"
        "    private MockMvc mockMvc;\n"
        "\n"
        + "\n\n".join(methods)
        + "\n}\n"
    )


def generate_api_tests(
    target: Path, endpoints: list[ApiEndpoint], lang: str, api_framework: str, module_path: str
) -> str:
    if not endpoints:
        return ""
    if lang == "python":
        return generate_api_test_python(target, endpoints, api_framework, module_path)
    if lang in ("typescript", "javascript"):
        return generate_api_test_ts(target, endpoints, api_framework)
    if lang == "go":
        return generate_api_test_go(target, endpoints, api_framework)
    if lang == "java":
        return generate_api_test_java(target, endpoints)
    return ""


def resolve_api_test_path(target: Path, lang: str, root: Path) -> Path:
    stem, ext, d = target.stem, target.suffix, target.parent
    if lang == "python":
        candidates = [p for p in root.glob("**/test_*.py") if "node_modules" not in str(p)]
        test_dir = candidates[0].parent if candidates else root
        return test_dir / f"test_{stem}_api.py"
    if lang in ("typescript", "javascript"):
        return d / f"{stem}.api.test{ext}"
    if lang == "go":
        return d / f"{stem}_api_test.go"
    if lang == "java":
        sr = str(target).replace(str(root / "src/main/java") + "/", "")
        return root / "src/test/java" / sr.replace(".java", "ApiTest.java")
    return d / f"{stem}.api.test{ext}"


# ── Claude: void/side-effect methods only ────────────────────────────────────

def call_claude(prompt: str) -> str:
    r = subprocess.run(["claude", "--print"], input=prompt, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"Claude failed:\n{r.stderr}")
    return r.stdout.strip()


def fill_void_bodies_with_claude(test_file_content: str, source_code: str, lang: str) -> str:
    if "TODO:CLAUDE_FILL" not in test_file_content:
        return test_file_content

    prompt = f"""A test file has been auto-generated. Some test bodies are marked TODO:CLAUDE_FILL.
These are for void/side-effect methods where mock verification cannot be inferred automatically.

Rules:
- Replace each TODO:CLAUDE_FILL comment with real assertions (mock.assert_called_once_with(...), etc.)
- Do NOT change anything else — keep all imports, mock setup, method names exactly as-is
- When/Then structure must be preserved
- Method names stay as-is

## Source file
{source_code}

## Test file (fill TODO:CLAUDE_FILL sections only)
{test_file_content}

Output ONLY the complete updated test file. No explanation, no markdown fences."""

    return call_claude(prompt)


# ── incremental: find uncovered methods ──────────────────────────────────────

def find_uncovered_methods(info_: SourceInfo, test_file: Path) -> list[MethodInfo]:
    test_content = test_file.read_text()
    uncovered = []
    for method in info_.methods:
        # check if method name appears in test file
        if method.name not in test_content:
            uncovered.append(method)
    return uncovered


# ── test output path ──────────────────────────────────────────────────────────

def resolve_test_path(target: Path, lang: str, root: Path, integration: bool) -> Path:
    stem, ext, d = target.stem, target.suffix, target.parent

    if integration:
        if lang in ("typescript", "javascript"): return d / f"{stem}.integration.test{ext}"
        if lang == "python":
            p = root / "tests" / "integration"; p.mkdir(parents=True, exist_ok=True)
            return p / f"test_{target.name}"
        if lang == "go":   return d / f"{stem}_integration_test.go"
        if lang == "java":
            sr = str(target).replace(str(root / "src/main/java") + "/", "")
            return root / "src/test/java" / sr.replace(".java", "IT.java")
    else:
        if lang in ("typescript", "javascript"): return d / f"{stem}.test{ext}"
        if lang == "python":
            candidates = [p for p in root.glob("**/test_*.py") if "node_modules" not in str(p)]
            test_dir = candidates[0].parent if candidates else root
            return test_dir / f"test_{target.name}"
        if lang == "go":   return d / f"{stem}_test.go"
        if lang == "java":
            sr = str(target).replace(str(root / "src/main/java") + "/", "")
            return root / "src/test/java" / sr.replace(".java", "Test.java")
        if lang == "ruby":
            spec_dir = root / "spec"
            rel = str(target).replace(str(root / "lib") + "/", "").replace(str(root / "app") + "/", "")
            return spec_dir / rel.replace(".rb", "_spec.rb")

    return d / f"{stem}.test{ext}"


# ── coverage ──────────────────────────────────────────────────────────────────

def run_coverage(lang: str, framework: str, test_file: Path, root: Path, threshold: int) -> bool:
    info(f"Running coverage (threshold: {threshold}%)...")
    try:
        if lang == "python":
            module = test_file.stem.replace("test_", "")
            r = subprocess.run(
                ["python", "-m", "pytest", str(test_file),
                 f"--cov={module}", "--cov-report=term-missing",
                 f"--cov-fail-under={threshold}"],
                cwd=root, capture_output=True, text=True,
            )
            print(r.stdout)
            return r.returncode == 0

        if lang in ("typescript", "javascript") and framework == "jest":
            r = subprocess.run(
                ["npx", "jest", "--coverage",
                 f'--coverageThreshold={{"global":{{"lines":{threshold}}}}}',
                 "--testPathPattern", test_file.name],
                cwd=root, capture_output=True, text=True,
            )
            print(r.stdout)
            return r.returncode == 0

        if lang == "go":
            pkg = test_file.parent
            r = subprocess.run(["go", "test", "-v", "-cover", "-coverprofile=coverage.out", "./..."], cwd=pkg)
            if r.returncode != 0: return False
            cov = subprocess.run(["go", "tool", "cover", "-func=coverage.out"],
                                  cwd=pkg, capture_output=True, text=True)
            for line in cov.stdout.splitlines():
                if line.startswith("total:"):
                    return float(line.split()[-1].rstrip("%")) >= threshold

    except FileNotFoundError as e:
        info(f"Coverage tool not found ({e}), skipping.")
    return False


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--api", action="store_true", help="Generate API/HTTP endpoint tests")
    parser.add_argument("--coverage", type=int, default=int(os.getenv("COVERAGE_THRESHOLD", "90")))
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        die(f"File not found: {target}")

    root = project_root(target)
    lang = detect_lang(target)
    framework = detect_framework(lang, root)

    info(f"Language: {lang} / {framework}")

    # ── API mode ───────────────────────────────────────────────────────────────
    source_text = target.read_text()
    api_framework = detect_api_framework(source_text, lang, root)

    if args.api or api_framework:
        if not api_framework:
            die("No API routes detected in this file.")
        info(f"API framework: {api_framework}")
        endpoints = detect_api_endpoints(source_text, lang, api_framework)
        info(f"Endpoints found: {[(e.method, e.path) for e in endpoints]}")
        if not endpoints:
            die("No endpoints detected. Check the file contains route definitions.")

        try:
            rel = target.relative_to(root).with_suffix("")
            module_path = ".".join(rel.parts)
        except ValueError:
            module_path = target.stem

        content = generate_api_tests(target, endpoints, lang, api_framework, module_path)
        test_path = resolve_api_test_path(target, lang, root)
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(content)
        info(f"API test written: {test_path}")
        info(f"Done: {test_path}")
        return

    # static analysis
    src_info = analyze_source(target, lang, root)
    info(f"Methods found: {[m.name for m in src_info.methods]}")
    info(f"External deps: {[d.name for d in src_info.external_deps]}")
    void_methods = [m for m in src_info.methods if m.is_void and not m.raises]
    info(f"Void methods (Claude needed): {[m.name for m in void_methods]}")

    test_path = resolve_test_path(target, lang, root, args.integration)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    info(f"Test output: {test_path}")

    # incremental mode
    if test_path.exists():
        info("Existing test file found — checking for uncovered methods...")
        uncovered = find_uncovered_methods(src_info, test_path)
        if not uncovered:
            info("All methods covered. Nothing to add.")
            return
        info(f"Uncovered: {[m.name for m in uncovered]}")
        # generate only for uncovered — temporarily filter
        src_info.methods = uncovered

    # generate skeleton (static analysis only)
    content = generate_test_file(target, root, src_info, framework, args.coverage)

    if not content:
        # fallback for unsupported languages
        info("Language not fully supported for static generation — delegating to Claude.")
        content = call_claude(
            f"Generate a complete test file for:\n{target.read_text()}\n"
            f"Language: {lang}, Framework: {framework}. "
            "Output ONLY the test file, no markdown fences."
        )
    else:
        info("Skeleton generated by static analysis.")
        # fill void method bodies with Claude (minimal call)
        if void_methods:
            info(f"Calling Claude for {len(void_methods)} void method(s) only...")
            content = fill_void_bodies_with_claude(content, target.read_text(), lang)
        else:
            info("No Claude call needed.")

    # write test file
    if test_path.exists():
        # append new tests
        existing = test_path.read_text()
        test_path.write_text(existing.rstrip() + "\n\n" + content)
    else:
        test_path.write_text(content)

    info(f"Written: {test_path}")

    # coverage
    if not args.integration:
        if run_coverage(lang, framework, test_path, root, args.coverage):
            info(f"Coverage ≥ {args.coverage}% achieved.")
        else:
            info(f"Coverage below {args.coverage}% — calling Claude for missing branches...")
            retry = call_claude(
                f"Tests did not achieve {args.coverage}% coverage. Add tests for missing branches.\n"
                f"Keep all existing tests. Same naming/When-Then rules.\n\n"
                f"## Test file\n{test_path.read_text()}\n\n"
                f"## Source\n{target.read_text()}\n\n"
                "Output ONLY the complete revised test file."
            )
            test_path.write_text(retry)
            if run_coverage(lang, framework, test_path, root, args.coverage):
                info(f"Coverage ≥ {args.coverage}% achieved after retry.")
            else:
                info("WARNING: Coverage target not met. Review manually.")

    info(f"Done: {test_path}")


if __name__ == "__main__":
    main()
