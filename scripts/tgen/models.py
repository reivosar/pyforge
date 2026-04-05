"""Core data structures for the test generator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BranchCase:
    test_name: str               # e.g. "raiseValueError_whenUserIdIsNegative"
    input_overrides: dict        # arg_name -> repr string  e.g. {"user_id": "-1"}
    mock_side_effect: str | None # exception class name to set as side_effect
    mock_return_override: str | None  # repr to set as return_value
    expected_exception: str | None
    expected_return: str | None  # repr string or None
    is_happy_path: bool
    expected_exception_match: str | None = None  # re.escape'd message for match=r"..."


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
