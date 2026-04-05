"""Python AST-based source analysis (first-class support)."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

from tgen.models import BranchCase, ClassInfo, DepInfo, MethodInfo, OrmModelInfo, SourceInfo


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


# ── usage-based type inference ────────────────────────────────────────────────

_STR_METHODS = {"strip", "upper", "lower", "split", "join", "replace", "startswith",
                "endswith", "format", "encode", "decode", "find", "count", "index"}
_LIST_METHODS = {"append", "extend", "pop", "remove", "insert", "sort", "reverse",
                 "index", "count"}
_DICT_METHODS = {"get", "keys", "values", "items", "update", "setdefault", "pop"}


def _infer_types_from_usage(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    arg_names: list[str],
    existing: dict[str, str],
    defaults: dict[str, str],
) -> dict[str, str]:
    """
    Infer arg types not already annotated by examining:
      1. Default values (arg=0 → int, arg="" → str, etc.)
      2. Comparison operators (arg > 0 → int, arg == "" → str)
      3. Attribute / method calls (arg.strip() → str, arg.append() → list)
      4. Arithmetic operators (+, -, *, /) → int or float (default int)
      5. len(arg) usage → str or list (default list)
      6. for x in arg → list
    """
    inferred: dict[str, str] = {}
    unknown = set(arg_names) - set(existing)
    if not unknown:
        return inferred

    # 1. defaults
    _DEFAULT_TYPE: dict[str, str] = {}
    for arg, default_repr in defaults.items():
        if arg not in existing and arg in unknown:
            d = default_repr.strip()
            if d.lstrip("-").isdigit():
                _DEFAULT_TYPE[arg] = "int"
            elif re.match(r'^-?\d+\.\d+$', d):
                _DEFAULT_TYPE[arg] = "float"
            elif d.startswith(("'", '"')):
                _DEFAULT_TYPE[arg] = "str"
            elif d in ("True", "False"):
                _DEFAULT_TYPE[arg] = "bool"
            elif d in ("[]", "list()"):
                _DEFAULT_TYPE[arg] = "list"
            elif d in ("{}", "dict()"):
                _DEFAULT_TYPE[arg] = "dict"
            elif d == "None":
                pass  # Optional — don't force a type
    inferred.update(_DEFAULT_TYPE)
    # refine unknown set with what we've inferred so far
    unknown = unknown - set(inferred)

    if not unknown:
        return inferred

    # 2-6. body walk
    scores: dict[str, dict[str, int]] = {a: {} for a in unknown}

    def vote(arg: str, typ: str, weight: int = 1) -> None:
        if arg in scores:
            scores[arg][typ] = scores[arg].get(typ, 0) + weight

    for child in ast.walk(node):
        # Comparisons: arg op constant
        if isinstance(child, ast.Compare):
            left = child.left
            if isinstance(left, ast.Name) and left.id in unknown:
                for op, comp in zip(child.ops, child.comparators):
                    if isinstance(comp, ast.Constant):
                        if isinstance(comp.value, (int, float)) and not isinstance(comp.value, bool):
                            vote(left.id, "int" if isinstance(comp.value, int) else "float", 2)
                        elif isinstance(comp.value, str):
                            vote(left.id, "str", 2)
            # right side
            for comp in child.comparators:
                if isinstance(comp, ast.Name) and comp.id in unknown:
                    if isinstance(child.left, ast.Constant):
                        if isinstance(child.left.value, (int, float)) and not isinstance(child.left.value, bool):
                            vote(comp.id, "int" if isinstance(child.left.value, int) else "float", 2)

        # Attribute access: arg.method(...)
        if (isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id in unknown):
            meth = child.attr
            if meth in _STR_METHODS:
                vote(child.value.id, "str", 3)
            elif meth in _LIST_METHODS:
                vote(child.value.id, "list", 3)
            elif meth in _DICT_METHODS:
                vote(child.value.id, "dict", 3)

        # len(arg)
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "len"
                and child.args
                and isinstance(child.args[0], ast.Name)
                and child.args[0].id in unknown):
            vote(child.args[0].id, "list", 1)  # could be str too, but list is safer default

        # for x in arg
        if isinstance(child, (ast.For, ast.AsyncFor)):
            if isinstance(child.iter, ast.Name) and child.iter.id in unknown:
                vote(child.iter.id, "list", 2)

        # Arithmetic: arg + / - / * / /
        if isinstance(child, ast.BinOp):
            for operand in (child.left, child.right):
                if isinstance(operand, ast.Name) and operand.id in unknown:
                    other = child.right if operand is child.left else child.left
                    if isinstance(child.op, ast.Add):
                        if isinstance(other, ast.Constant) and isinstance(other.value, str):
                            vote(operand.id, "str", 2)
                        elif isinstance(other, ast.Constant) and isinstance(other.value, float):
                            vote(operand.id, "float", 2)
                        elif isinstance(other, ast.Constant) and isinstance(other.value, int) and not isinstance(other.value, bool):
                            vote(operand.id, "int", 1)
                    elif isinstance(child.op, (ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
                        if isinstance(other, ast.Constant) and isinstance(other.value, float):
                            vote(operand.id, "float", 2)
                        elif isinstance(other, ast.Constant) and isinstance(other.value, int) and not isinstance(other.value, bool):
                            vote(operand.id, "int", 1)

    for arg, type_scores in scores.items():
        if type_scores:
            best = max(type_scores, key=lambda t: type_scores[t])
            inferred[arg] = best

    return inferred


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

    # Fill in missing type hints via usage inference
    inferred = _infer_types_from_usage(node, arg_names, arg_types, arg_defaults)
    for arg, typ in inferred.items():
        if arg not in arg_types:
            arg_types[arg] = typ

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


def detect_orm_models(target: Path) -> list[OrmModelInfo]:
    """Return OrmModelInfo for each ORM model class defined in target.

    Detects:
    - SQLAlchemy: class inheriting from *Base / db.Model / DeclarativeBase
    - Django: class inheriting from models.Model / Model
    psycopg2 raw SQL has no model classes — returns [].
    """
    _SA_BASES = {"Base", "db.Model", "DeclarativeBase"}
    _SA_COLUMN_FUNCS = {"Column", "mapped_column", "relationship"}
    _DJ_BASES = {"models.Model", "Model"}
    _DJ_FIELD_SUFFIXES = ("Field",)
    _DJ_RELATION_FUNCS = {"ForeignKey", "ManyToManyField", "OneToOneField"}

    try:
        tree = ast.parse(target.read_text())
    except SyntaxError:
        return []

    result: list[OrmModelInfo] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [ast.unparse(b) for b in node.bases]

        # SQLAlchemy
        if any(b.endswith("Base") or b in _SA_BASES for b in bases):
            col_attrs: list[str] = []
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    rhs = stmt.value
                    if isinstance(rhs, ast.Call):
                        func_name = ast.unparse(rhs.func).split(".")[-1]
                        if func_name in _SA_COLUMN_FUNCS:
                            for t in stmt.targets:
                                if isinstance(t, ast.Name):
                                    col_attrs.append(t.id)
            result.append(OrmModelInfo(node.name, "sqlalchemy", col_attrs))
            continue

        # Django
        if any(b in _DJ_BASES for b in bases):
            field_attrs: list[str] = []
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    rhs = stmt.value
                    if isinstance(rhs, ast.Call):
                        func_name = ast.unparse(rhs.func).split(".")[-1]
                        if func_name.endswith(_DJ_FIELD_SUFFIXES) or func_name in _DJ_RELATION_FUNCS:
                            for t in stmt.targets:
                                if isinstance(t, ast.Name):
                                    field_attrs.append(t.id)
            result.append(OrmModelInfo(node.name, "django", field_attrs))

    return result


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
