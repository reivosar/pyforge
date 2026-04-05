"""Test case generation package — unified generate_cases() entry point."""
from __future__ import annotations

from pyforge.cases.branch import analyze_method_branches
from pyforge.cases.combinatorial import (
    default_arg_cases,
    enum_cases,
    null_combination_cases,
    pairwise_cases,
    union_type_cases,
)
from pyforge.cases.extreme import extreme_value_cases
from pyforge.models import BranchCase, MethodInfo

TIER_GENERATORS: dict[str, set[str]] = {
    "minimal": {
        "branch",
        "happy_path",
    },
    "standard": {
        "branch",
        "happy_path",
        "boundary",   # embedded inside analyze_method_branches
        "null",
        "defaults",
        "enum",
    },
    "exhaustive": {
        "branch",
        "happy_path",
        "boundary",
        "null",
        "defaults",
        "enum",
        "pairwise",
        "union",
        "extreme",
        "hypothesis",
    },
}


def generate_cases(
    method: MethodInfo,
    enum_types: dict[str, list[str]],
    mode: str = "standard",
) -> list[BranchCase]:
    """
    Return all BranchCases for a method at the given tier.
    Note: hypothesis tests are NOT included (they need rendering context).
    """
    active = TIER_GENERATORS.get(mode, TIER_GENERATORS["standard"])
    cases: list[BranchCase] = []

    branch_cases = analyze_method_branches(method)
    if mode == "minimal":
        branch_cases = [
            b for b in branch_cases
            if b.expected_exception is not None
            or (b.expected_return is not None and not b.is_happy_path)
            or b.is_happy_path
        ]
    cases.extend(branch_cases)

    if "null" in active:
        cases.extend(null_combination_cases(method))
    if "enum" in active:
        cases.extend(enum_cases(method, enum_types))
    if "pairwise" in active:
        cases.extend(pairwise_cases(method))
    if "defaults" in active:
        cases.extend(default_arg_cases(method))
    if "union" in active:
        cases.extend(union_type_cases(method))
    if "extreme" in active:
        cases.extend(extreme_value_cases(method))

    return cases
