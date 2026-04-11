"""Combinatorial test case generators: null, enum, pairwise, defaults, union."""
from __future__ import annotations

import re

from pyforge.analysis.python_ast import (
    SAMPLE_VALUES,
    _type_sample,
    is_base,
    is_nullable,
    parse_type,
    type_sample,
    unwrap_optional,
    UnionType,
)
from pyforge.cases.branch import _camel
from pyforge.models import BranchCase, MethodInfo


def _parse_union_members(type_hint: str) -> list[str]:
    """
    Parse union type hint strings and return list of member type names.
    Handles Union[...], Optional[...], and X|Y syntax.
    Returns empty list for non-union types.
    """
    if not type_hint or not isinstance(type_hint, str):
        return []

    # Handle Optional[X] -> "str, None"
    if type_hint.startswith("Optional["):
        inner = type_hint[9:-1]  # Remove "Optional[" and "]"
        return [inner.strip(), "None"]

    # Handle Union[X, Y, Z]
    if type_hint.startswith("Union["):
        inner = type_hint[6:-1]  # Remove "Union[" and "]"
        members = [m.strip() for m in inner.split(",")]
        return members

    # Handle X | Y | Z syntax
    if " | " in type_hint:
        members = [m.strip() for m in type_hint.split(" | ")]
        return members

    # Not a union type
    return []


def null_combination_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each nullable arg (Optional[X], X | None, or untyped), generate one BranchCase
    with that arg=None. Only activates when the method has ≥2 args.
    """
    if len(method.args) < 2:
        return []
    nullable = [
        a for a in method.args
        if is_nullable(parse_type(method.arg_types.get(a)))
    ]
    return [
        BranchCase(
            test_name=f"raiseOrReturnNone_when{_camel(null_arg)}IsNone",
            input_overrides={null_arg: "None"},
            mock_side_effect=None, mock_return_override=None,
            expected_exception=None, expected_return=None,
            is_happy_path=False,
        )
        for null_arg in nullable
    ]


def enum_cases(method: MethodInfo, enum_types: dict[str, list[str]]) -> list[BranchCase]:
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


def pairwise_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For methods with ≥3 args, generate the minimum set of test rows that
    covers every (arg_i=v_i, arg_j=v_j) pair using a greedy algorithm.
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
        v2 = repr(vs[2]) if len(vs) > 2 else None
        values[arg] = [v0, v1] + ([v2] if v2 and v2 != v0 else [])

    uncovered: set[tuple] = set()
    for i in range(len(args)):
        for j in range(i + 1, len(args)):
            for vi in values[args[i]]:
                for vj in values[args[j]]:
                    uncovered.add((args[i], vi, args[j], vj))

    rows: list[dict[str, str]] = []
    while uncovered:
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
            break
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


def default_arg_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each arg with a default value, generate tests with the explicit default
    and an alternate non-default value.
    """
    if not method.arg_defaults:
        return []
    cases: list[BranchCase] = []
    for arg, default_repr in method.arg_defaults.items():
        arg_label = _camel(arg)
        cases.append(BranchCase(
            test_name=f"complete_when{arg_label}IsDefault{_camel(re.sub(r'[^a-zA-Z0-9]', '_', default_repr[:16]))}",
            input_overrides={arg: default_repr},
            mock_side_effect=None, mock_return_override=None,
            expected_exception=None, expected_return=None,
            is_happy_path=False,
        ))
        t = parse_type(method.arg_types.get(arg, ""))
        inner = unwrap_optional(t)

        # Handle Union types by picking the first concrete member
        if isinstance(inner, UnionType):
            concrete = [m for m in inner.members if not is_base(m, "none")]
            inner = concrete[0] if concrete else inner

        if is_base(inner, "bool"):
            alt = "False" if default_repr.strip() == "True" else "True"
        elif is_base(inner, "str"):
            alt = '""' if default_repr.strip() != '""' else '"alt"'
        elif is_base(inner, "int") or is_base(inner, "float"):
            # For int/float, use a safe non-boundary value (not 0 which often fails validation)
            try:
                is_int = is_base(inner, "int")
                default_val = int(default_repr.strip()) if is_int else float(default_repr.strip())
                if default_val > 1:
                    alt = str(default_val // 2) if is_int else str(default_val / 2)
                else:
                    alt = "1" if is_int else "1.0"
            except (ValueError, ZeroDivisionError):
                alt = "1" if is_base(inner, "int") else "1.0"
        elif is_base(inner, "list"):
            alt = "[]" if default_repr.strip() != "[]" else "[1, 2, 3]"
        elif default_repr.strip() == "None":
            # For Optional[ExternalType] = None, use MagicMock() as non-default
            sample = type_sample(inner)
            if sample == "None":
                # External type (like TodoStatus) - use MagicMock()
                alt = "MagicMock()"
            else:
                alt = sample
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


def union_type_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each arg with a Union / Optional / X|Y type hint,
    generate one BranchCase per concrete member type.
    """
    cases: list[BranchCase] = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "")
        t = parse_type(hint)
        if not isinstance(t, UnionType):
            continue
        # Get non-None members
        concrete = [m for m in t.members if not is_base(m, "none")]
        if len(concrete) < 2:
            continue
        for member in concrete:
            sample = type_sample(member)
            if sample == "None":
                continue
            # Format member name for test: BaseType("str") → "Str"
            from pyforge.analysis.python_ast import BaseType, GenericType, UnknownType
            if isinstance(member, BaseType):
                member_name = member.name.capitalize()
            elif isinstance(member, GenericType):
                member_name = member.name
            elif isinstance(member, UnknownType):
                member_name = _camel(member.raw)
            else:
                member_name = "Value"
            cases.append(BranchCase(
                test_name=f"complete_when{_camel(arg)}Is{member_name}",
                input_overrides={arg: sample},
                mock_side_effect=None, mock_return_override=None,
                expected_exception=None, expected_return=None,
                is_happy_path=False,
            ))
    return cases
