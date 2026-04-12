"""pyforge — public library API."""
from __future__ import annotations

from pyforge.analysis.python_ast import analyze_python, detect_enum_types, project_root
from pyforge.cases import generate_cases
from pyforge.renderers.pytest_renderer import generate_python_test_file
from pyforge.renderers.api_renderer import generate_api_tests, detect_api_framework
from pyforge.renderers.db_integration_renderer import generate_db_integration_block
from pyforge.coverage import (
    run_coverage,
    resolve_test_path,
    resolve_api_test_path,
    find_uncovered_methods,
    parse_missing_lines,
    project_root_from_path,
)
from pyforge.models import SourceInfo, ClassInfo, MethodInfo, BranchCase, DepInfo, OrmModelInfo

__all__ = [
    "analyze_python",
    "detect_enum_types",
    "project_root",
    "generate_cases",
    "generate_python_test_file",
    "generate_api_tests",
    "detect_api_framework",
    "generate_db_integration_block",
    "run_coverage",
    "resolve_test_path",
    "resolve_api_test_path",
    "find_uncovered_methods",
    "parse_missing_lines",
    "project_root_from_path",
    "SourceInfo",
    "ClassInfo",
    "MethodInfo",
    "BranchCase",
    "DepInfo",
    "OrmModelInfo",
]
