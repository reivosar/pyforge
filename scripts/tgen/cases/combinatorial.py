"""Combinatorial test case generators: null, enum, pairwise, defaults, union."""
from __future__ import annotations

import re

from tgen.analysis.python_ast import SAMPLE_VALUES, _type_sample
from tgen.cases.branch import _camel
from tgen.models import BranchCase, MethodInfo


def null_combination_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each nullable arg (Optional[X] or untyped), generate one BranchCase
    with that arg=None. Only activates when the method has ≥2 args.
    """
    if len(method.args) < 2:
        return []
    nullable = [
        a for a in method.args
        if not method.arg_types.get(a) or "Optional" in method.arg_types.get(a, "")
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
    """Extract member types from Union[X, Y] or X | Y."""
    hint = hint.strip()
    m = re.match(r"Union\[(.+)\]$", hint)
    if m:
        return [t.strip() for t in m.group(1).split(",")]
    if "|" in hint and not hint.startswith("Optional"):
        parts = [p.strip() for p in hint.split("|")]
        if len(parts) >= 2:
            return parts
    m2 = re.match(r"Optional\[(.+)\]$", hint)
    if m2:
        return [m2.group(1).strip(), "None"]
    return []


def union_type_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For each arg with a Union / Optional / X|Y type hint,
    generate one BranchCase per concrete member type.
    """
    cases: list[BranchCase] = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "")
        members = _parse_union_members(hint)
        concrete = [m for m in members if m not in ("None", "NoneType")]
        if len(concrete) < 2:
            continue
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
